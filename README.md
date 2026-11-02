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
│   ├── base
│   │   ├── namespace.yaml
│   │   ├── configmap.yaml
│   │   ├── pvc.yaml
│   │   ├── deployment.yaml
│   │   ├── service.yaml
│   │   └── kustomization.yaml
│   └── overlays
│       └── minikube
│           ├── kustomization.yaml
│           └── resources-patch.yaml
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