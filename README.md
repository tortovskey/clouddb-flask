# CloudDB

CloudDB - учебная облачная информационная система на Flask с serverless-консолью для виртуальных баз данных, схем, записей, аудита, экспорта, SQLite snapshots и backup/restore.

## Возможности

- регистрация и вход пользователей;
- изолированные рабочие пространства: пользователь видит только свои базы, таблицы, записи и backups;
- создание виртуальных баз данных и таблиц с JSON-схемами;
- типы колонок: `text`, `number`, `boolean`, `date`, `json`;
- добавление, редактирование, удаление, фильтрация и сортировка записей;
- предсказуемая сортировка по типу колонки, включая числовую сортировку;
- глобальный поиск по базам, таблицам и записям;
- импорт массива записей через JSON;
- экспорт таблиц в JSON и CSV;
- скачивание выбранной виртуальной базы как SQLite snapshot;
- создание backup, скачивание backup в SQLite и восстановление backup в новую базу с суффиксом `Restored`;
- dashboard с метриками autoscaling, regions, function invocations, storage usage, backup status и audit log.

## SQLite Snapshots

Кнопка `Download DB` скачивает не сырой файл `database.db`, а отдельный изолированный SQLite snapshot выбранной виртуальной базы.

Snapshot содержит таблицы:

- `snapshot_meta`;
- `tables`;
- `records`;
- `activity_events`.

В snapshot не попадают `users`, `password_hash` и данные других пользователей. Raw `database.db` не скачивается из UI по соображениям изоляции пользователей.

## Backup / Restore

В разделе `Backups` можно:

- выбрать базу данных;
- создать backup;
- скачать backup как `.sqlite`;
- восстановить backup в новую CloudDB-базу.

Restore не перезаписывает существующие базы и записи.

## Запуск

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

Открыть в браузере:

```text
http://127.0.0.1:5000
```

Если порт `5000` занят, можно запустить Flask на другом порту:

```powershell
python -m flask --app app run --host 127.0.0.1 --port 5001
```

SQLite-файл приложения создается автоматически как `database.db`.

## Конфигурация

Для production-подобного запуска задайте `SECRET_KEY` через переменную окружения. Пример находится в `.env.example`. Локальный `database.db`, логи и runtime-файлы намеренно исключены из Git.

Для HTTPS-развёртывания также задайте:

```text
SESSION_COOKIE_SECURE=True
```
