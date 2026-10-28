#!/usr/bin/env python3
"""Фоновый запуск существующего QA: проверки в worktree и Ollama."""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import fcntl
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import urllib.request

import qa_agent as qa

STOP = threading.Event()
HEALTH = qa.HERE / 'service-status.json'
RETRIES = qa.HERE / 'retries.json'


def atomic_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix('.tmp')
    with tmp.open('w') as out:
        json.dump(data, out, ensure_ascii=False, indent=2)
        out.flush()
        os.fsync(out.fileno())
    tmp.replace(path)


def health(status: str, **extra) -> None:
    atomic_json(HEALTH, {'status': status, 'pid': os.getpid(),
                        'at': dt.datetime.now(dt.timezone.utc).isoformat(), **extra})


class LogStream:
    def __init__(self, logger):
        self.logger = logger
        self.buffer = ''

    def write(self, text):
        self.buffer += text
        while '\n' in self.buffer:
            line, self.buffer = self.buffer.split('\n', 1)
            if line.strip():
                self.logger.info(line)
        return len(text)

    def flush(self):
        if self.buffer:
            self.logger.info(self.buffer)
            self.buffer = ''


class Tunnel:
    """Собственный SSH-туннель; не трогает туннели и сервисы пользователя."""
    def __init__(self):
        self.proc = None

    def ensure(self):
        tunnel = qa.CONFIG.get('ssh_tunnel')
        if tunnel and (self.proc is None or self.proc.poll() is not None):
            self.proc = subprocess.Popen([
                '/usr/bin/ssh', '-NT', '-o', 'BatchMode=yes',
                '-o', 'ConnectTimeout=10', '-o', 'ExitOnForwardFailure=yes',
                '-o', 'ServerAliveInterval=30', '-o', 'ServerAliveCountMax=3',
                '-L', tunnel['forward'],
                tunnel['host']], stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 15
        while not STOP.is_set() and time.monotonic() < deadline:
            if self.proc and self.proc.poll() is not None:
                raise RuntimeError('SSH-туннель завершился; повторю позже')
            try:
                with urllib.request.urlopen(qa.CONFIG['ollama_url'] + '/api/tags', timeout=3) as response:
                    names = {m['name'] for m in json.load(response)['models']}
                if qa.CONFIG['model'] not in names and qa.CONFIG['model'] + ':latest' not in names:
                    raise RuntimeError('В Ollama отсутствует настроенная QA-модель')
                return
            except (OSError, ValueError):
                STOP.wait(0.5)
        raise RuntimeError('Ollama недоступен; задачи остаются в очереди Freejira')

    def close(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=5)


def cycle(fj, tunnel, retries: dict, inspect_only=False):
    jobs = []
    for key in qa.CONFIG['projects']:
        project = qa.Project.from_config(key)
        if not project.repo.is_dir():
            raise RuntimeError(f'{key}: репозиторий отсутствует: {project.repo}')
        tasks = fj.call('list_tasks', status='review', project_id=project.freejira_project_id)
        jobs.extend((project, t) for t in tasks)
    if inspect_only:
        tunnel.ensure()
        return {'projects': list(qa.CONFIG['projects']), 'review_tasks': len(jobs),
                'model': qa.CONFIG['model'], 'ollama': 'connected'}
    state = qa.load_state()
    for project, task in jobs:
        if STOP.is_set():
            break
        ref = task['id']
        retry = retries.get(ref, {})
        if retry.get('revision') == task['revision'] and retry.get('after', 0) > time.time():
            continue
        key = f"{project.key}-{task['number']}"
        health('checking', task=key)
        try:
            tunnel.ensure()
            qa.process(fj, project, ref, apply=True, force=False, state=state)
            retries.pop(ref, None)
        except Exception as error:
            count = retry.get('count', 0) + 1
            retries[ref] = {'count': count, 'revision': task['revision'],
                            'after': time.time() + min(1800, qa.CONFIG.get('retry_seconds', 120) * 2 ** min(count - 1, 4))}
            qa.log(f'{key}: {type(error).__name__}: {error}; повтор запланирован')
        atomic_json(RETRIES, retries)
    active = {t['id'] for _, t in jobs}
    retries = {k: v for k, v in retries.items() if k in active}
    atomic_json(RETRIES, retries)
    health('waiting', review_tasks=len(jobs), retry_tasks=len(retries),
           poll_seconds=qa.CONFIG.get('poll_seconds', 30), projects=list(qa.CONFIG['projects']))
    return retries


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--inspect', action='store_true', help='Только проверить доступ, без QA и записи')
    parser.add_argument('--once', action='store_true', help='Один проход с публикацией отчётов')
    parser.add_argument('--config', help='Private configuration file')
    args = parser.parse_args()
    qa.configure(args.config)
    global HEALTH, RETRIES
    HEALTH = qa.HERE / 'service-status.json'
    RETRIES = qa.HERE / 'retries.json'

    lock = qa.acquire_lock()
    signal.signal(signal.SIGTERM, lambda *_: STOP.set())
    signal.signal(signal.SIGINT, lambda *_: STOP.set())
    tunnel = Tunnel()
    if args.inspect:
        fj = qa.Freejira()
        try:
            print(json.dumps(cycle(fj, tunnel, {}, True), ensure_ascii=False))
        finally:
            fj.close()
            tunnel.close()
        return
    logger = logging.getLogger('freejira-qa')
    logger.setLevel(logging.INFO)
    handler = RotatingFileHandler(qa.HERE / 'service.log', maxBytes=5_000_000, backupCount=3)
    handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
    logger.addHandler(handler)
    retries = json.loads(RETRIES.read_text()) if RETRIES.exists() else {}
    stream = LogStream(logger)
    with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
        qa.log(f"QA service started; interval {qa.CONFIG.get('poll_seconds', 30)}s")
        try:
            while not STOP.is_set():
                fj = None
                try:
                    fj = qa.Freejira()
                    retries = cycle(fj, tunnel, retries)
                except Exception as error:
                    qa.log(f'Временно недоступно: {type(error).__name__}: {error}')
                    health('retrying', error=str(error)[:500])
                finally:
                    if fj:
                        try:
                            fj.close()
                        except Exception as error:
                            qa.log(f'Закрытие соединения: {error}')
                if args.once:
                    break
                STOP.wait(qa.CONFIG.get('poll_seconds', 30))
        finally:
            tunnel.close()
            health('stopped')
            stream.flush()


if __name__ == '__main__':
    main()
