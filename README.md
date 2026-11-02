# DeepSeek vLLM CPU Kubernetes Deployment

Локальное развёртывание OpenAI-совместимого API для модели `deepseek-ai/deepseek-coder-1.3b-instruct` с использованием vLLM и Kubernetes.

Проект запускается на CPU в Minikube и включает:

- rootless Docker-образ vLLM;
- отдельный rootless initContainer для загрузки модели;
- PersistentVolumeClaim для сохранения весов;
- Kubernetes Secret для Hugging Face и API-токенов;
- ConfigMap для параметров инференса;
- Bearer-аутентификацию;
- фильтрацию чувствительных данных из логов;
- Kustomize-манифесты;
- readiness, liveness и startup probes.

## Архитектура

```text
Пользователь
    │
    │ Authorization: Bearer <API token>
    ▼
kubectl port-forward
    │
    ▼
Service vllm:8000
    │
    ▼
Deployment vllm
    ├── initContainer model-downloader
    │      ├── получает HF_TOKEN из Secret
    │      ├── проверяет маркер .complete
    │      └── скачивает модель в PVC
    │
    └── container vllm
           ├── запускается от UID 10001
           ├── читает модель из PVC
           ├── получает VLLM_API_KEY из Secret
           └── предоставляет OpenAI-совместимый API
```

## Используемые компоненты

| Компонент | Значение |
|---|---|
| Модель | `deepseek-ai/deepseek-coder-1.3b-instruct` |
| vLLM | `0.31.0` |
| Устройство | CPU |
| Тип данных | `bfloat16` |
| Kubernetes | Minikube |
| Контейнерный runtime | Docker |
| API | OpenAI-compatible |
| Локальный API-порт | `18000` |
| Kubernetes Service | `8000` |

## Требования

Для локального запуска рекомендуется:

- Windows 11 с WSL2;
- Docker Desktop;
- Minikube;
- kubectl;
- Git;
- минимум 16 ГБ RAM;
- минимум 8 логических CPU;
- не менее 20 ГБ свободного дискового пространства.

Тестовое окружение:

```text
Host RAM: 15.6 ГБ
Minikube RAM: 10 ГБ
Minikube CPU: 8
WSL swap: 4 ГБ
```

## Структура проекта

```text
.
├── Dockerfile
├── Dockerfile.downloader
├── requirements.in
├── requirements.txt
├── downloader-requirements.in
├── downloader-requirements.txt
├── config
│   └── logging_config.json
├── src
│   └── redacting_filter.py
├── scripts
│   └── download_model.py
├── bench
│   └── load_test.py
├── k8s
│   └── base
│       ├── namespace.yaml
│       ├── configmap.yaml
│       ├── pvc.yaml
│       ├── deployment.yaml
│       ├── service.yaml
│       └── kustomization.yaml
├── secret.env.example
└── README.md
```

## Настройка WSL2

Для компьютера с 16 ГБ RAM в `%UserProfile%\.wslconfig` использовалась конфигурация:

```ini
[wsl2]
memory=11GB
processors=10
swap=4GB
```

После изменения конфигурации необходимо выполнить:

```powershell
wsl --shutdown
```

Затем перезапустить Docker Desktop.

## Запуск Minikube

```powershell
minikube start `
  --driver=docker `
  --cpus=8 `
  --memory=10240 `
  --disk-size=30g
```

Проверка:

```powershell
minikube status
kubectl get nodes
kubectl get storageclass
```

## Сборка Docker-образов

### Загрузчик модели

```powershell
docker build `
  --file Dockerfile.downloader `
  --tag deepseek-downloader:0.1.0 `
  .
```

### Сервер vLLM

```powershell
docker build `
  --tag deepseek-vllm:0.1.1 `
  .
```

### Проверка rootless-пользователя

```powershell
docker run --rm `
  --entrypoint id `
  deepseek-downloader:0.1.0
```

```powershell
docker run --rm `
  --entrypoint id `
  deepseek-vllm:0.1.1
```

Ожидаемый UID:

```text
uid=10001(app) gid=10001(app)
```

## Загрузка образов в Minikube

```powershell
minikube image load deepseek-downloader:0.1.0
minikube image load deepseek-vllm:0.1.1
```

Проверка:

```powershell
minikube image ls |
  Select-String -Pattern "deepseek"
```

## Создание Secret

Реальный `secret.env` не хранится в Git.

Создайте локальный файл на основе `secret.env.example`:

```dotenv
HF_TOKEN=replace_with_hugging_face_read_token
VLLM_API_KEY=replace_with_random_api_token
```

Сначала создайте Namespace:

```powershell
kubectl apply -f k8s/base/namespace.yaml
```

Создайте или обновите Secret:

```powershell
kubectl create secret generic llm-secrets `
  --namespace llm `
  --from-env-file=secret.env `
  --dry-run=client `
  -o yaml |
kubectl apply -f -
```

Проверка без раскрытия значений:

```powershell
kubectl describe secret llm-secrets -n llm
```

Secret должен содержать два ключа:

```text
HF_TOKEN
VLLM_API_KEY
```

## Развёртывание

Предварительная проверка:

```powershell
kubectl apply `
  -k k8s/base `
  --dry-run=client
```

Развёртывание:

```powershell
kubectl apply -k k8s/base
```

Наблюдение:

```powershell
kubectl get pods -n llm -w
```

Первый запуск включает:

1. скачивание модели init-контейнером;
2. загрузку весов;
3. CPU-компиляцию;
4. прогрев модели;
5. запуск HTTP API.

Процесс может занимать несколько минут.

Проверка Deployment:

```powershell
kubectl rollout status `
  deployment/vllm `
  -n llm `
  --timeout=30m
```

Успешное состояние:

```text
READY   STATUS    RESTARTS
1/1     Running   0
```

## Просмотр логов

Получите имя Pod:

```powershell
$PodName = kubectl get pods `
  -n llm `
  -l app.kubernetes.io/name=deepseek-vllm `
  -o jsonpath="{.items[0].metadata.name}"
```

Логи загрузчика:

```powershell
kubectl logs `
  -n llm `
  $PodName `
  -c model-downloader
```

Логи vLLM:

```powershell
kubectl logs `
  -n llm `
  $PodName `
  -c vllm `
  -f
```

## Подключение к API

Локальный порт `18000` используется, чтобы избежать конфликтов с другими приложениями на порту `8000`.

```powershell
kubectl port-forward `
  -n llm `
  service/vllm `
  18000:8000
```

API будет доступен по адресу:

```text
http://127.0.0.1:18000
```

## Проверка health endpoint

```powershell
curl.exe -i http://127.0.0.1:18000/health
```

Ожидается:

```text
HTTP/1.1 200 OK
```

## Проверка аутентификации

Без токена:

```powershell
curl.exe -i http://127.0.0.1:18000/v1/models
```

Ожидается:

```text
HTTP/1.1 401 Unauthorized
```

Загрузка API-токена из Kubernetes Secret:

```powershell
$EncodedApiKey = kubectl get secret llm-secrets `
  -n llm `
  -o jsonpath="{.data.VLLM_API_KEY}"

$env:VLLM_API_KEY = [System.Text.Encoding]::UTF8.GetString(
  [System.Convert]::FromBase64String($EncodedApiKey)
)

Remove-Variable EncodedApiKey
```

С токеном:

```powershell
curl.exe -i `
  http://127.0.0.1:18000/v1/models `
  -H "Authorization: Bearer $env:VLLM_API_KEY"
```

Ожидается:

```text
HTTP/1.1 200 OK
```

## Запрос к модели

```powershell
$Headers = @{
  Authorization = "Bearer $env:VLLM_API_KEY"
}

$RequestBody = @{
  model = "deepseek-coder"
  messages = @(
    @{
      role = "user"
      content = "Ответь одним коротким предложением: что такое Kubernetes?"
    }
  )
  max_tokens = 64
  temperature = 0.2
  stream = $false
} | ConvertTo-Json -Depth 5

$Response = Invoke-RestMethod `
  -Uri "http://127.0.0.1:18000/v1/chat/completions" `
  -Method Post `
  -Headers $Headers `
  -ContentType "application/json; charset=utf-8" `
  -Body $RequestBody `
  -TimeoutSec 600

$Response.choices[0].message.content
```

## Безопасное логирование

Логируется:

- HTTP-метод;
- путь endpoint;
- HTTP-статус;
- факт обращения к модели.

Не логируется:

- пользовательский prompt;
- сообщения пользователя;
- сгенерированный ответ;
- HF-токен;
- API-токен.

Проверка отсутствия prompt:

```powershell
kubectl logs `
  -n llm `
  $PodName `
  -c vllm `
  --since=10m |
Select-String -Pattern "что такое Kubernetes"
```

Правильный результат — пустой вывод.

## Проверка повторного запуска

Во время проверки использовались:

```text
Старый Pod: vllm-58bf8488b-bq5bb
Новый Pod: vllm-58bf8488b-zh849
PVC после перезапуска: Bound
Downloader: download skipped
Health после восстановления: 200 OK
```

Для повторения проверки:

```powershell
$OldPodName = kubectl get pods `
  -n llm `
  -l app.kubernetes.io/name=deepseek-vllm `
  -o jsonpath="{.items[0].metadata.name}"

kubectl delete pod $OldPodName -n llm
```

После создания нового Pod:

```powershell
$NewPodName = kubectl get pods `
  -n llm `
  -l app.kubernetes.io/name=deepseek-vllm `
  -o jsonpath="{.items[0].metadata.name}"

kubectl logs `
  -n llm `
  $NewPodName `
  -c model-downloader
```

Ожидается:

```text
Model is already present in persistent storage; download skipped
```

Это подтверждает, что веса загружаются с PVC без повторного обращения к Hugging Face.

## Результаты функционального тестирования

| Проверка | Результат |
|---|---|
| Pod запущен | `1/1 Running` |
| Health endpoint | `200 OK` |
| `/v1/models` без токена | `401 Unauthorized` |
| `/v1/models` с токеном | `200 OK` |
| Chat completion | Успешно |
| Prompt отсутствует в логах | Успешно |
| Ответ отсутствует в логах | Успешно |
| PVC после удаления Pod | `Bound` |
| Повторная загрузка модели | Пропущена |

## Меры безопасности

- контейнеры запускаются с UID/GID `10001`;
- запрещён запуск от root;
- `allowPrivilegeEscalation: false`;
- удалены все Linux capabilities;
- используется `RuntimeDefault` seccomp;
- root filesystem доступна только для чтения;
- writable-каталоги подключаются через отдельные volumes;
- Kubernetes Service имеет тип `ClusterIP`;
- Service Account Token не монтируется;
- API требует Bearer-токен;
- реальные секреты исключены из Git;
- основной контейнер не получает HF-токен;
- модель монтируется в основной контейнер read-only.

## Нагрузочное тестирование

Для измерения производительности используется скрипт `bench/load_test.py`. Он отправляет потоковые запросы к OpenAI-совместимому API и измеряет:

- **TTFT** — время от отправки запроса до первого содержательного токена;
- **Latency** — полное время выполнения запроса;
- **Requests/s** — количество завершённых запросов в секунду;
- **Output tok/s** — количество сгенерированных токенов в секунду;
- **Total tok/s** — суммарное количество обработанных входных и выходных токенов в секунду.

### Конфигурация теста

| Параметр | Значение |
|---|---:|
| Модель | `deepseek-coder-1.3b-instruct` |
| vLLM | `0.31.0` |
| Устройство | CPU |
| Лимит CPU контейнера | `8` |
| Лимит памяти контейнера | `7 GiB` |
| `MAX_MODEL_LEN` | `2048` |
| `MAX_NUM_SEQS` | `2` |
| `MAX_NUM_BATCHED_TOKENS` | `512` |
| `VLLM_CPU_KVCACHE_SPACE` | `1 GiB` |
| `OMP_NUM_THREADS` | `8` |
| Запросов на сценарий | `6` |
| Конкурентность | `2` |
| Максимум выходных токенов | `32` |
| Температура | `0` |

Перед тестом выполняется один прогревочный запрос каждого размера. Прогревочные запросы в итоговую статистику не включаются.

Короткий промпт содержал в среднем `108` токенов, длинный — `1232` токена. Для снижения влияния prefix cache каждый промпт содержал уникальный идентификатор.

### Запуск теста

Сначала необходимо запустить перенаправление порта:

```powershell
kubectl port-forward -n llm service/vllm 18000:8000
```

В другом терминале получить API-токен из Kubernetes Secret:

```powershell
$EncodedToken = kubectl get secret llm-secrets `
  -n llm `
  -o jsonpath="{.data.VLLM_API_KEY}"

$env:VLLM_API_KEY = [System.Text.Encoding]::UTF8.GetString(
  [System.Convert]::FromBase64String($EncodedToken)
)

Remove-Variable EncodedToken
```

Запустить тест:

```powershell
python bench/load_test.py `
  --base-url http://127.0.0.1:18000 `
  --model deepseek-coder `
  --requests 6 `
  --concurrency 2 `
  --max-tokens 32 `
  --timeout 600
```

После завершения удалить токен из текущего окружения:

```powershell
if (Test-Path Env:VLLM_API_KEY) {
    Remove-Item Env:VLLM_API_KEY
}
```

Подробный JSON-отчёт сохраняется локально в `bench/results/load-test.json`. Каталог с результатами исключён из Git.

### Результаты

| Промпт | Средний input, токенов | TTFT p50, с | TTFT p95, с | Latency p50, с | Latency p95, с | Requests/s | Output tok/s | Total tok/s |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Короткий | 108 | 12.021 | 12.831 | 18.431 | 18.566 | 0.109 | 3.48 | 15.23 |
| Длинный | 1232 | 105.224 | 144.872 | 159.374 | 182.655 | 0.013 | 0.41 | 16.08 |

Все 12 измеряемых запросов завершились успешно, без HTTP-ошибок и тайм-аутов.

### Анализ результатов

Длинный промпт содержал примерно в `11.4` раза больше входных токенов. По сравнению с коротким сценарием:

- медианный TTFT увеличился приблизительно в `8.8` раза;
- медианная полная задержка увеличилась приблизительно в `8.6` раза;
- пропускная способность по запросам уменьшилась приблизительно в `8.5` раза;
- пропускная способность генерации уменьшилась с `3.48` до `0.41` выходного токена в секунду.

При этом `Total tok/s` у длинного сценария немного выше: `16.08` против `15.23`. Это не означает, что длинные запросы обслуживаются быстрее. В этой метрике учитываются все входные токены, а длинный сценарий передаёт серверу значительно больше текста за один запрос. С точки зрения пользователя TTFT, полная задержка и скорость выдачи ответа заметно хуже.

Значение p95 рассчитано только по шести запросам каждого типа, поэтому тест следует считать исследовательским. Для более строгого сравнения конфигураций необходимо увеличить число запросов и выполнить несколько независимых запусков.

### Настройка для большого потока коротких запросов

Если поступает много запросов с небольшим количеством токенов, основная цель — увеличить размер динамического батча и количество одновременно обрабатываемых последовательностей.

Возможные изменения:

1. Постепенно увеличить `MAX_NUM_SEQS` с `2` до `4`, а затем до `8`. Это позволит планировщику одновременно обрабатывать больше запросов. После каждого изменения необходимо повторять тест, поскольку слишком высокая конкурентность на восьми CPU может привести к конкуренции потоков и ухудшению latency.

2. Увеличить `MAX_NUM_BATCHED_TOKENS` с `512` до `1024` или `2048`, чтобы за одну итерацию обрабатывалось больше токенов от разных запросов.

3. Добавить параметр:

   ```text
   --performance-mode throughput
   ```

   Этот режим ориентирован на совокупную пропускную способность при высокой конкурентности.

4. Проверить увеличение `VLLM_CPU_KVCACHE_SPACE`. Более крупный KV cache позволяет обслуживать больше параллельных последовательностей, но требует соответствующего увеличения лимита памяти Pod.

5. Не занимать все доступные CPU OpenMP-потоками. При лимите в восемь CPU можно протестировать `OMP_NUM_THREADS=7`, оставив один CPU для API-сервера, токенизации и служебных потоков vLLM.

6. Если запросы имеют большой общий системный промпт или одинаковый префикс, prefix caching может уменьшить повторную обработку входных токенов.

Для данного сценария наиболее важным первым экспериментом будет комбинация:

```text
MAX_NUM_SEQS=4
MAX_NUM_BATCHED_TOKENS=1024
OMP_NUM_THREADS=7
```

### Настройка для небольшого числа запросов с большим контекстом

Для длинных запросов основная нагрузка приходится на prefill — обработку входного контекста до генерации первого токена.

Возможные изменения:

1. Увеличить `MAX_NUM_BATCHED_TOKENS` с `512` до `1024` или `2048`. Текущий длинный промпт содержит `1232` токена, поэтому при бюджете `512` его prefill приходится разбивать на несколько итераций. Более крупный токенный бюджет потенциально уменьшит TTFT.

2. Сохранить chunked prefill включённым. Он позволяет разбивать длинные входы на части и совмещать их обработку с decode уже выполняющихся запросов.

3. Если требуется контекст больше текущих `2048` токенов, увеличить `MAX_MODEL_LEN` до значения, поддерживаемого моделью. Изменение необходимо выполнять вместе с контролем потребления памяти.

4. Увеличить `VLLM_CPU_KVCACHE_SPACE` с `1` до `2` GiB или больше, одновременно повысив лимит памяти Pod. Увеличение только переменной KV cache без доступной памяти может привести к завершению контейнера по OOM.

5. Оставить `MAX_NUM_SEQS` небольшим, например `1` или `2`, поскольку для этого сценария высокая конкурентность не является основной целью.

6. Prefix caching особенно полезен, если длинные запросы содержат одинаковый документ, системную инструкцию или другой повторяющийся префикс.

Для данного сценария первым экспериментом может быть:

```text
MAX_NUM_SEQS=2
MAX_NUM_BATCHED_TOKENS=2048
MAX_MODEL_LEN=2048
VLLM_CPU_KVCACHE_SPACE=2
```

Перед увеличением KV cache необходимо увеличить доступную Pod память и проверить её фактическое потребление.

## Известные предупреждения

При запуске на CPU могут появляться предупреждения:

```text
get_mempolicy: Operation not permitted
numa_migrate_pages failed
Failed to create oneDNN linear, fallback to torch linear
```

Они связаны с ограниченным security context и отсутствием некоторых CPU-оптимизаций. На корректность инференса не влияют.

## Остановка

Остановить только inference:

```powershell
kubectl scale deployment/vllm `
  -n llm `
  --replicas=0
```

Запустить снова:

```powershell
kubectl scale deployment/vllm `
  -n llm `
  --replicas=1
```

Остановить Minikube:

```powershell
minikube stop
```

## Полное удаление

Удалить Kubernetes-ресурсы:

```powershell
kubectl delete -k k8s/base
```

Эта команда удалит PVC и сохранённую модель.

Полностью удалить Minikube:

```powershell
minikube delete
```

## Лицензии

Перед использованием модели необходимо ознакомиться с лицензией `deepseek-ai/deepseek-coder-1.3b-instruct` и лицензиями используемых зависимостей.
