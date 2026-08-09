# Face Access System — CV/ML System Design

Проект системы распознавания лиц для проходных офисного кампуса.

Цель системы — ускорить проход сотрудников и снизить нагрузку на охрану, сохраняя консервативную политику безопасности: сомнительный результат распознавания никогда не приводит к автоматическому открытию турникета.

## Что делает решение

Система обрабатывает событие с камеры по следующему pipeline:

`camera → face detection → quality → alignment → liveness → embedding → ANN search → Decision Engine → turnstile / manual review`

Предусмотрены три результата:

- `allow` — уверенное совпадение, проверки пройдены, доступ разрешён;
- `manual_review` — недостаточно уверенности для безопасного автоматического прохода;
- `deny` — подтверждённый запрет или явно небезопасный сценарий.

False Accept рассматривается как более дорогая ошибка, чем False Reject. Поэтому при неопределённости система выбирает безопасный fallback вместо автоматического открытия.

## Архитектурный подход

Выбран **edge-first / hybrid** подход.

На edge-узле проходной выполняется latency-critical hot path:

- face detection;
- quality assessment;
- alignment;
- liveness;
- embedding extraction;
- поиск по локальному ANN-индексу;
- Decision Engine.

Это позволяет стремиться к целевому `p95 < 1 s` и уменьшает зависимость проходной от сети.

Центральная часть отвечает за:

- lifecycle сотрудников;
- обновление biometric templates;
- access policies и revoke events;
- централизованный audit;
- monitoring;
- распространение моделей и конфигураций.

При небезопасном degraded mode автоматический `allow` запрещается.

## PoC

В репозитории находится минимальный работающий прототип:

`poc.py`

PoC проверяет Decision Engine и два обязательных сценария.

### Happy path

Хорошее качество кадра, успешный liveness и уверенный match сотрудника.

Ожидаемый результат:

```text
decision: allow
turnstile_command: open
```
### Risky path

Система работает в offline-режиме с устаревшим кэшем.

Ожидаемый результат:

```text
decision: manual_review
turnstile_command: keep_closed
```
### Запуск PoC
```bash
python3 poc.py
```
При успешном выполнении smoke-тестов программа выводит:
```text
    Smoke tests: PASSED
```
