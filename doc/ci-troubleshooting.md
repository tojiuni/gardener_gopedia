# CI 트러블슈팅 가이드

Woodpecker CI (ci.toji.homes) + Dagger 파이프라인에서 발생할 수 있는 문제와 해결 방법을 정리합니다.

---

## 파이프라인 구조

```
.woodpecker/ci.yml
  ├─ validate-pr   (pull_request)        → Dagger Docker build 검증 (push 없음)
  └─ build-push    (push/tag/manual)     → Dagger build + registry push
```

`ci/run.py` → Dagger `_validate()` / `_build_and_push()` → `Dockerfile`

---

## 알려진 문제

---

### CI-01: validate-pr exit code 1 — gcc 누락 + `[eval]` 과도 설치

**현상**

- `validate-pr` 단계가 약 6–7분 실행 후 exit code 1로 실패
- Woodpecker 로그 마지막 줄에 pip 컴파일 오류 또는 네트워크 타임아웃

**원인 (복합)**

| # | 원인 | 패키지 |
|---|------|--------|
| 1 | `python:3.12-slim` 에 `gcc` 없음 | `ir-measures` → `pytrec-eval-terrier` C 확장 컴파일 실패 |
| 2 | `pip install ".[eval]"` 다운로드 과부하 | `ragas` → `langchain` 계열 200+ 패키지, 빌드 시간 초과 |
| 3 | fallback `\|\| pip install .` 도 1번 오류로 실패 | 두 번 모두 실패 → exit 1 |

구 Dockerfile (문제):

```dockerfile
RUN apt-get install -y libpq5            # gcc 없음
RUN pip install --no-cache-dir ".[eval]" || pip install --no-cache-dir .
#   ↑ ragas 다운로드 → 타임아웃 or 실패
#   ↑ fallback도 pytrec-eval-terrier 컴파일 실패
```

**해결** ([gardener_gopedia#16](https://github.com/tojiuni/gardener_gopedia/pull/16))

```dockerfile
RUN apt-get install -y gcc build-essential libpq5   # C 확장 빌드 가능
RUN pip install --no-cache-dir .                    # [eval] 제외, 단순화
```

- `gcc build-essential` 추가 → `pytrec-eval-terrier` 컴파일 통과
- `[eval]` 제거 → ragas/openai/langfuse 는 K8s 런타임 불필요
- 불안정한 `||` fallback 패턴 제거

**로컬에서 재현**

```bash
# 문제 재현 (gcc 없는 환경에서)
docker build --no-cache --target=test \
  --build-arg PIP_ARGS=".[eval]" \
  . 2>&1 | grep -E "error:|Failed"

# 수정 후 검증
docker build --no-cache . && echo "OK"
```

---

### CI-02: Dagger `SessionError` — runner host 미설정

**현상**

```
dagger.SessionError: failed to connect to session ...
```

**원인**

`ci/run.py` 가 `DAGGER_RUNNER_HOST` 를 환경변수에서 읽어 설정하는데, Woodpecker step 의 `environment:` 블록이 누락되거나 서비스명이 다를 경우 발생합니다.

**확인**

```yaml
# .woodpecker/ci.yml — 모든 Dagger 사용 step에 아래가 있어야 함
environment:
  DAGGER_RUNNER_HOST: tcp://dagger-engine.dagger.svc.cluster.local:1234
```

`ci/run.py` 에서도 `_EXPERIMENTAL_DAGGER_RUNNER_HOST` 를 함께 설정합니다:

```python
os.environ["DAGGER_RUNNER_HOST"] = runner_host
os.environ["_EXPERIMENTAL_DAGGER_RUNNER_HOST"] = runner_host
```

두 변수 모두 없으면 Dagger가 로컬 socket을 찾아 실패합니다.

**해결**

```bash
# K8s에서 dagger-engine 서비스 확인
kubectl get svc -n dagger
# NAME            TYPE        CLUSTER-IP   PORT(S)
# dagger-engine   ClusterIP   10.x.x.x     1234/TCP
```

서비스가 다른 네임스페이스에 있거나 포트가 다르면 `.woodpecker/ci.yml` 의 `DAGGER_RUNNER_HOST` 값을 실제 주소로 수정합니다.

---

### CI-03: validate-pr 이 docs-only PR에서도 실행됨

**현상**

`doc/*.md` 만 수정한 PR에서도 `validate-pr` (Docker build) 이 실행되어 불필요하게 오래 걸립니다.

**원인**

`.woodpecker/ci.yml` 에 path filter 가 없어 모든 PR이 빌드 검증을 실행합니다.

**해결** ([gardener_gopedia#17](https://github.com/tojiuni/gardener_gopedia/pull/17))

```yaml
steps:
  - name: validate-pr
    when:
      - event: pull_request
        path:
          include:
            - "gardener_gopedia/**"
            - "Dockerfile"
            - "pyproject.toml"
            - "alembic/**"
            - "ci/**"
          exclude:
            - "doc/**"
            - "dataset/**"
            - "*.md"
```

`ci/**` 도 include에 추가해 CI 스크립트 변경 시 검증이 실행되도록 합니다.
path filter를 적용하면 코드 변경이 없는 PR에서는 빌드 단계를 건너뜁니다.

---

### CI-04: `registry_token` 미설정 — build-push 실패

**현상**

```
unauthorized: authentication required
```

또는 Woodpecker 로그에서 `REGISTRY_TOKEN` 이 비어 있는 오류.

**원인**

`tojiuni/gardener_gopedia` Woodpecker 레포에 `registry_token` secret이 등록되지 않았습니다.

**확인 및 해결**

```bash
export WOODPECKER_SERVER=https://ci.toji.homes
export WOODPECKER_TOKEN=<admin-api-token>  # secret/neunexus/woodpecker → admin-api-token

# 등록 여부 확인
woodpecker-cli repo secret ls --repo tojiuni/gardener_gopedia

# 없으면 등록 (neunexus .env 참고)
REGISTRY_TOKEN=$(vault kv get -field=token secret/neunexus/woodpecker.artifacts-push-token)
woodpecker-cli repo secret add \
  --repo tojiuni/gardener_gopedia \
  --name registry_token \
  --value "$REGISTRY_TOKEN" \
  --event push --event manual --event tag
```

> **참고**: Vault 경로 `secret/neunexus/woodpecker.artifacts-push-token`, 필드명 `token`

---

### CI-05: clone 단계가 60초 이상 소요

**현상**

pipeline의 `clone` 단계가 60–90초 걸립니다. (정상 레포 대비 느림)

**원인**

`dataset/` 디렉토리에 대용량 JSON 파일이 체크인되어 있습니다 (각 489KB, 6개 이상).
Woodpecker agent 가 전체 히스토리를 클론합니다.

**현재 상태**: 미적용 (Woodpecker 서버 제약으로 보류)

`clone:` 블록을 `.woodpecker/ci.yml` 에 추가하면 Woodpecker 린터가 다음 두 오류 중 하나로 파이프라인 전체를 block합니다:

| 설정 | 오류 |
|------|------|
| `image: woodpecker/plugin-git` 명시 | `Specified clone image does not match allow list, netrc is not injected` |
| `image:` 생략 | `Invalid or missing image` |

커스텀 `clone` 블록을 쓰려면 서버 설정 `WOODPECKER_PLUGINS_TRUSTED` 에 해당 이미지를 등록해야 합니다. 등록 전까지는 `clone:` 블록 없이 기본 full clone 을 사용합니다.

```bash
# Woodpecker 서버에서 (운영자 설정)
# WOODPECKER_PLUGINS_TRUSTED=woodpecker/plugin-git 환경변수 추가 후 재시작
```

> 현재 Woodpecker에서 clone 단계의 파일 필터링은 지원하지 않습니다.

---

## 로컬 Dagger 빌드로 디버깅

CI 실패를 로컬에서 재현하려면:

```bash
# 1. Dagger 설치
pip install dagger-io anyio

# 2. 로컬 Docker daemon 사용 (K8s runner 없이)
unset DAGGER_RUNNER_HOST
unset _EXPERIMENTAL_DAGGER_RUNNER_HOST

# 3. validate (build only, no push)
python ci/run.py validate

# 4. push 포함 빌드 (레지스트리 토큰 필요)
export REGISTRY_TOKEN=<token>
python ci/run.py build --sha=$(git rev-parse HEAD)
```

Dagger가 로컬 Docker daemon에 연결해 `Dockerfile` 을 빌드합니다. CI와 동일한 결과를 로컬에서 확인할 수 있습니다.

---

## 파이프라인 수동 재실행

PR 수정 없이 최신 파이프라인을 재실행하는 방법:

```bash
export WOODPECKER_SERVER=https://ci.toji.homes
export WOODPECKER_TOKEN=<admin-api-token>

# 파이프라인 번호 확인
woodpecker-cli pipeline ls tojiuni/gardener_gopedia

# 재실행
woodpecker-cli pipeline start tojiuni/gardener_gopedia <pipeline-number>
```

---

## 관련 문서

| 문서 | 내용 |
|------|------|
| [neunexus: woodpecker-cicd-setup.md](https://github.com/tojiuni/neunexus/blob/main/docs/runbooks/woodpecker-cicd-setup.md) | Woodpecker 전체 설정 가이드, Dagger 핵심 패턴 |
| [doc/k8s-deployment.md](k8s-deployment.md) | K8s 배포 구조, Vault 설정, ArgoCD |
| [Dockerfile](../Dockerfile) | 프로덕션 이미지 빌드 정의 |
| [.woodpecker/ci.yml](../.woodpecker/ci.yml) | 파이프라인 step 정의 |
