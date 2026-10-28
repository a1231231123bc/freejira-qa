# Freejira QA

Фоновый QA для [Freejira](https://github.com/a1231231123bc/freejira): задача попадает в «На проверке» → агент находит GitHub PR → запускает проверки → локальная модель Ollama сравнивает изменения с задачей → отчёт появляется в комментариях.

По умолчанию колонка не меняется. Агент не сливает PR и не делает деплой. Неопределённость, незавершённый CI или отсутствие успешных проверок не считаются успешной приёмкой.

## Установка

Нужны macOS/Linux, Python 3.10+, Git, GitHub CLI, Node 24+, Ollama с установленной моделью и доступ к Freejira. У модели и инструментов каждого проекта свои требования к памяти и зависимостям.

```sh
git clone https://github.com/a1231231123bc/freejira-qa.git
cd freejira-qa
python3 -m venv .venv
.venv/bin/python -m pip install .
mkdir -p ~/.config/freejira-qa
chmod 700 ~/.config/freejira-qa
cp config.example.json ~/.config/freejira-qa/config.json
chmod 600 ~/.config/freejira-qa/config.json
```

Заполните приватный конфиг: ключ и UUID проекта, путь к отдельному клону, GitHub-репозиторий, команды проверок, модель и MCP. Для Sites используйте [подключение](docs/mcp.md), для самостоятельного сервера — пример в [README](README.md#connect-freejira).

`trusted: false` отключает выполнение кода репозитория. Разрешайте его только для доверенных проектов: install/test-скрипты работают с правами пользователя сервиса. Worktree не изолирует файловую систему. Проверка чужих PR требует отдельной изолированной среды. Форки по умолчанию не исполняются.

```sh
.venv/bin/freejira-qa-service --inspect
.venv/bin/freejira-qa --task DEMO-1
.venv/bin/freejira-qa --task DEMO-1 --apply
.venv/bin/freejira-qa-service
```

Первые две команды не пишут в Freejira. Сервис публикует отчёты автоматически. Для запуска на отдельном Mac/M4 или Linux см. [автозапуск и перенос](docs/services.md). Все зависимости должны находиться на том компьютере: тогда основной ноутбук может быть выключен. LaunchAgent запускается после входа пользователя в macOS.

Состояние, логи и отчёты: `~/.local/state/freejira-qa`. Временные worktree: `~/.cache/freejira-qa/worktrees`. Не публикуйте их. Повторные проверки защищены от дублирования отчёта после потери ответа; одновременно должен работать только один агент на пространство.

Опрос выполняется каждые 30 секунд, пока агент свободен. Проверки идут последовательно. Это ранняя версия: заключение модели требует критической оценки человеком. [Ограничения](README.md#results-and-storage) · [MIT](LICENSE).
