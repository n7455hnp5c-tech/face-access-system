# ML Design

## 1. ML-задачи системы

CV/ML-конвейер состоит из последовательных этапов:

1. face detection;
2. quality assessment;
3. face alignment;
4. liveness / anti-spoofing;
5. извлечение face embedding;
6. поиск кандидатов в базе;
7. оценка match score и margin;
8. принятие решения `allow / manual_review / deny`.

Критический принцип: модель распознавания не должна непосредственно открывать турникет. Модели формируют оценки, а итоговое решение принимает отдельный Decision Engine с учётом качества, liveness, similarity, margin, прав доступа и состояния системы.

## 2. Detection, quality и alignment

### Face detection

Первый этап определяет наличие лица и bounding box. Для MVP используется готовая pretrained-модель, поскольку обучение собственного детектора не является целью проекта.

Если лицо не найдено, система может сделать ограниченное число повторных попыток по соседним кадрам. После этого событие переводится в `manual_review`, а турникет не открывается.

### Quality assessment

До распознавания проверяются факторы, влияющие на надёжность:

- освещённость;
- blur;
- размер лица;
- occlusion;
- положение головы;
- пригодность кадра для recognition.

Низкое качество не трактуется как «человек посторонний». Это недостаток доказательств для безопасного автоматического решения, поэтому предпочтителен retry или `manual_review`.

### Alignment

По facial landmarks лицо нормализуется перед вычислением embedding. Это уменьшает влияние масштаба, поворота и положения лица.

## 3. Liveness / anti-spoofing

Liveness является отдельным safety-gate перед recognition.

Система должна обнаруживать как минимум:

- фотографию на телефоне;
- распечатанную фотографию;
- replay-видео с экрана.

Для MVP допустим pretrained passive liveness detector либо mock-компонент. Для production решение выбирается на отдельном validation set с реальными presentation attacks.

При уверенном spoofing:

`decision = deny`

При пограничном liveness score:

`decision = manual_review`

Даже очень высокий face-match score не может компенсировать провал liveness.

В дальнейшем можно рассмотреть multi-frame passive liveness, анализ temporal cues или специализированные RGB/IR/depth-камеры, если passive RGB baseline не обеспечивает необходимый уровень безопасности.

## 4. Face embeddings

После alignment pretrained face-recognition model преобразует лицо в embedding фиксированной размерности.

Разумный baseline — готовая модель класса ArcFace/InsightFace либо эквивалентная pretrained face-embedding модель.

Обучать face-recognition model с нуля для MVP нецелесообразно:

- отсутствует собственный большой размеченный датасет;
- pretrained-модели дают сильный baseline;
- основной риск проекта связан не только с качеством embedding, но и с liveness, threshold policy, domain shift и эксплуатацией.

Перед production требуется валидация выбранной модели на данных, соответствующих реальным камерам кампуса.

## 5. Verification и identification

**Verification (1:1)** отвечает на вопрос:

> Является ли это лицо заявленным сотрудником X?

**Identification (1:N)** отвечает на вопрос:

> Кому из сотрудников базы принадлежит это лицо?

Для бесконтактного прохода без предъявления карты требуется identification, поскольку заранее неизвестен `employee_id`.

Система вычисляет embedding и ищет ближайших кандидатов среди разрешённых сотрудников.

Карта-пропуск может использоваться как fallback. В таком случае известен employee_id и возможен более простой 1:1 verification.

## 6. One-to-many search

Полный перебор по сотням тысяч embeddings нежелателен с точки зрения масштабирования.

Используется ANN — Approximate Nearest Neighbor index.

Возможные реализации:

- FAISS;
- HNSW;
- другой локальный vector index.

На edge хранится локальный индекс актуальных разрешённых biometric templates.

По запросу извлекается несколько ближайших кандидатов (`top-k`), после чего Decision Engine анализирует:

- score первого кандидата;
- score второго кандидата;
- margin между ними;
- access policy найденного employee_id.

ANN является механизмом поиска кандидатов, а не самостоятельным механизмом принятия решения.

## 7. Три исхода и пороги

Используются два уровня уверенности вместо одного бинарного threshold.

Обозначим similarity лучшего кандидата как `S1`, второго — `S2`, а:

`margin = S1 - S2`.

### Allow

Автоматический проход возможен только если:

- quality >= Q_allow;
- liveness >= L_allow;
- S1 >= T_allow;
- margin >= M_allow;
- право доступа действительно;
- система не находится в небезопасном degraded mode.

### Manual review

Используется для серой зоны:

- `T_review <= S1 < T_allow`;
- недостаточный margin;
- пограничный liveness;
- среднее качество;
- неоднозначный кандидат;
- offline со слишком старым кешем.

Турникет остаётся закрытым до fallback-проверки.

### Deny

Используется при:

- уверенном spoofing;
- отсутствии действующего права доступа;
- score значительно ниже `T_review`;
- невозможности получить пригодное лицо после retry.

Конкретные численные значения `T_allow`, `T_review`, `L_allow` и `M_allow` нельзя корректно выбрать без validation data. В PoC используются демонстрационные значения, а production thresholds выбираются экспериментально.

## 8. False Accept и False Reject

Ошибки имеют несимметричную стоимость.

**False Accept (FA)** — посторонний ошибочно получает доступ. Это security incident.

**False Reject (FR)** — сотрудник ошибочно не получает автоматический доступ. Это ухудшает UX, увеличивает очередь и нагрузку на охрану, но существует безопасный fallback.

Поэтому оптимизация должна быть cost-sensitive: threshold `allow` выбирается прежде всего при жёстком ограничении на FAR, а затем минимизируется FRR.

Для серой зоны используется `manual_review`, что позволяет не превращать каждую неопределённость ни в опасный `allow`, ни в окончательный `deny`.

## 9. Метрики

Основные ML-метрики:

- FAR — False Accept Rate;
- FRR — False Reject Rate;
- TAR/TPR при заданном FAR;
- ROC;
- EER как диагностическая метрика;
- доля `manual_review`;
- liveness Attack Presentation Classification Error Rate / attack detection rate;
- quality rejection rate;
- latency каждого ML-компонента;
- end-to-end p95 latency.

Одного accuracy недостаточно из-за разной стоимости ошибок.

Для identification дополнительно измеряются Recall@1 / Recall@k на корректной identity-disjoint validation procedure.

## 10. Validation set

Validation set должен отражать реальные условия эксплуатации:

- разные камеры;
- разные проходные;
- разные дни;
- утро/вечер;
- нормальное, слабое и контровое освещение;
- очки;
- маски;
- головные уборы;
- разные head poses;
- реальные spoofing-сценарии.

### Split без leakage

Нельзя случайно делить соседние кадры одного видеопотока между train и validation: они почти идентичны и дадут завышенную оценку.

Для оценки обобщающей способности компонентов, которые дообучаются, применяется split по identity: личности в соответствующих train/validation частях не пересекаются.

При настройке recognition thresholds отдельно формируются genuine и impostor pairs/search events из независимых сессий, камер и дней. Несколько кадров одного прохода не должны одновременно попадать по разные стороны сплита.

Финальная проверка проводится на временно отложенном наборе данных, максимально близком к production.

## 11. Проверка подгрупп

Общая метрика может скрывать систематические проблемы.

Метрики анализируются отдельно по:

- камере и проходной;
- освещению;
- наличию очков/маски;
- head pose;
- quality buckets;
- другим допустимым и юридически корректным группам, необходимым для проверки качества и fairness.

Если отдельная группа имеет существенно более высокий FRR или FAR, автоматический rollout останавливается до расследования причины.

## 12. Delayed labels

Истинный результат некоторых событий становится известен позднее.

Источники delayed labels:

- решение охраны после `manual_review`;
- успешный проход по карте после face reject;
- жалоба сотрудника;
- подтверждённый security incident;
- расследование spoofing.

Эти события связываются с исходным `event_id` и используются для последующего мониторинга и переоценки thresholds.

Важно учитывать шум labels: например, проход по карте после face reject является сильным сигналом возможного false reject, но не абсолютным доказательством без дополнительной проверки.

## 13. Что решает модель, а что правила

### ML

- face detection;
- quality estimation;
- liveness;
- embedding extraction;
- similarity/search.

### Rules / Decision Engine

- пороги;
- margin requirement;
- access policy;
- cache freshness;
- degraded-mode policy;
- retry;
- перевод на manual review;
- команда турникету.

Такое разделение делает safety-критичное решение более контролируемым и аудируемым.

## 14. Baseline

Первый технический baseline:

1. pretrained face detector;
2. landmarks + alignment;
3. pretrained ArcFace-подобный embedding model;
4. cosine similarity;
5. локальный FAISS/HNSW index;
