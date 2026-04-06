# conjira-cli

셀프 호스팅 환경의 Confluence와 Jira를 위한 비공식, 에이전트 친화적 CLI입니다.

English version: [README.md](README.md)

`conjira-cli`는 Confluence와 Jira를 사내 또는 자체 인프라에서 운영하는 팀이 스크립트, 로컬 코딩 에이전트, Markdown 워크플로에서 실용적으로 사용할 수 있도록 만든 작은 Python CLI입니다. 표준 Atlassian REST API를 단순한 명령줄 인터페이스로 감싸고, 로컬 자격 증명 관리를 더 안전하게 하며, 쓰기 작업에는 기본 안전장치를 둡니다.

이 저장소는 공개용으로 정리된 상태입니다. 실제 회사 URL, PAT, 프로젝트 키, 페이지 ID, 이슈 키, 내보낸 사내 데이터는 포함하지 않습니다.

이 저장소는 꼭 Python 개발자만 쓰는 용도는 아닙니다. 대환님처럼 로컬 코딩 에이전트나 셸을 실행할 수 있는 AI 도구를 쓰고 있다면, 이 레포와 `agent.env`를 에이전트에게 주고 “이 Confluence 페이지를 Markdown으로 export해줘”, “오래된 위키 복사본을 최신 상태로 갱신해줘”, “이번 주 생성된 Jira 이슈를 찾아줘”처럼 자연어로 요청해도 됩니다. 에이전트는 이 README와 `docs/AGENT_USAGE.md`를 보고 필요한 CLI 명령을 대신 실행할 수 있습니다.

## 어떤 문제를 해결하나요

셀프 호스팅 Confluence와 Jira를 쓰는 팀은 공식 클라우드 커넥터만으로는 부족한 경우가 많습니다. REST API는 있지만, 로컬 셸이나 코딩 에이전트에서 쉽게 재사용할 수 있는 얇은 도구가 없는 경우가 흔합니다.

`conjira-cli`는 그 틈을 메우기 위해 만들었습니다. Confluence 페이지 읽기, Markdown 내보내기, 오래된 export 갱신, 인라인 코멘트 스레드 요약, Jira JQL 검색, 문서와 이슈 생성 및 수정 같은 작업을 PAT를 소스 파일이나 채팅에 직접 남기지 않고 처리할 수 있습니다.

## 할 수 있는 일

- Confluence 페이지 조회와 CQL 검색
- Confluence 페이지를 노트 시스템, 문서 폴더, 지식관리용 Markdown으로 export
- storage HTML 또는 Markdown으로 Confluence 페이지 생성 및 수정
- 오래된 Markdown export 검사 및 최신 위키 기준 refresh
- Confluence 인라인 코멘트 스레드 조회 및 Markdown export
- Confluence 첨부파일 업로드
- Jira 이슈 조회, JQL 검색, create metadata 조회, 이슈 생성, 댓글 추가
- `--allow-write`와 allowlist 기반의 쓰기 안전장치

## 누가 쓰면 좋나요

이 도구는 특히 셀프 호스팅 Atlassian 환경, 즉 Server나 Data Center 스타일 배포에 잘 맞습니다. 현재 검증된 경로는 self-hosted base URL과 Bearer PAT 기반 인증이며, Atlassian Cloud보다 온프레미스 패턴에 더 가깝습니다. 참고 문서는 [Atlassian Cloud basic auth](https://developer.atlassian.com/cloud/jira/service-desk/basic-auth-for-rest-apis/) 와 [Atlassian Personal Access Tokens](https://confluence.atlassian.com/enterprise/using-personal-access-tokens-1026032365.html) 입니다.

## 데모

Confluence와 Jira 인증 확인:

```bash
./bin/conjira --env-file ./local/agent.env auth-check
./bin/conjira --env-file ./local/agent.env jira-auth-check
```

Confluence 페이지를 Markdown으로 export:

```bash
./bin/conjira --env-file ./local/agent.env export-page-md --page-id 123456 --output-dir "/path/to/notes"
```

Markdown 파일로 Confluence 페이지 생성:

```bash
./bin/conjira --env-file ./local/agent.env create-page --allow-write --space-key DOCS --parent-id 100001 --title "Markdown page" --body-markdown-file ./notes/demo.md
```

기존 export가 오래됐는지 확인하고 최신 위키 내용으로 갱신:

```bash
./bin/conjira --env-file ./local/agent.env check-page-md-freshness --file "/path/to/notes/page.md"
./bin/conjira --env-file ./local/agent.env refresh-page-md --file "/path/to/notes/page.md"
```

Confluence 인라인 코멘트 스레드 요약 export:

```bash
./bin/conjira --env-file ./local/agent.env export-inline-comments-md --page-id 123456 --status open --output-dir "/path/to/notes"
```

Jira 검색과 이슈 조회:

```bash
./bin/conjira --env-file ./local/agent.env jira-search --jql 'project = DEMO ORDER BY created DESC' --limit 5
./bin/conjira --env-file ./local/agent.env jira-get-issue --issue-key DEMO-123
```

예시 출력은 아래처럼 짧고 단순한 JSON 형태입니다. 아래 값은 모두 synthetic example입니다.

```json
{
  "base_url": "https://confluence.example.com",
  "authenticated": true,
  "space_count_sample": 1,
  "first_space_key": "DOCS"
}
```

```json
{
  "page_id": "123456",
  "title": "Quarterly planning notes",
  "output_file": "/path/to/notes/Quarterly planning notes.md",
  "source_url": "https://confluence.example.com/pages/viewpage.action?pageId=123456",
  "used_staging_local": false
}
```

```json
{
  "key": "DEMO-123",
  "summary": "Roll out the new onboarding flow",
  "status": "In Progress",
  "issue_type": "Task",
  "assignee": "Alex Kim",
  "browse_url": "https://jira.example.com/browse/DEMO-123"
}
```

## 5분 안에 시작하기

```bash
git clone https://github.com/quanttraderkim/conjira-cli.git
cd conjira-cli
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
pip install -e .
```

아직 설치하지 않아도 저장소에 포함된 wrapper로 바로 실행할 수 있습니다.

```bash
./bin/conjira --help
./bin/conjira-cli --help
```

로컬 설정 파일은 이렇게 만듭니다.

```bash
cp ./local/agent.env.example ./local/agent.env
```

## 자격 증명 관리

운영체제에 따라 권장 방식이 조금 다릅니다.

macOS에서는 PAT를 Keychain에 넣고, `local/agent.env`에는 base URL이나 export 경로 같은 비밀이 아닌 값만 두는 구성이 가장 편합니다.

```dotenv
CONFLUENCE_BASE_URL=https://confluence.example.com
CONFLUENCE_PAT_KEYCHAIN_SERVICE=conjira-cli
CONFLUENCE_PAT_KEYCHAIN_ACCOUNT=confluence-prod
CONFLUENCE_EXPORT_DEFAULT_DIR=/path/to/notes/Confluence Inbox
CONFLUENCE_EXPORT_STAGING_DIR=/absolute/path/to/conjira-cli/local/exports

JIRA_BASE_URL=https://jira.example.com
JIRA_PAT_KEYCHAIN_SERVICE=conjira-cli
JIRA_PAT_KEYCHAIN_ACCOUNT=jira-prod
```

Confluence PAT를 Keychain에 저장:

```bash
read -s "PAT?Enter Confluence PAT: "; echo
security add-generic-password -U -s conjira-cli -a confluence-prod -w "$PAT"
unset PAT
```

Jira PAT를 Keychain에 저장:

```bash
read -s "PAT?Enter Jira PAT: "; echo
security add-generic-password -U -s conjira-cli -a jira-prod -w "$PAT"
unset PAT
```

Linux나 Windows에서는 Keychain 대신 환경변수나 token file을 쓰면 됩니다.

```dotenv
CONFLUENCE_BASE_URL=https://confluence.example.com
CONFLUENCE_PAT=your-confluence-pat
CONFLUENCE_EXPORT_DEFAULT_DIR=/path/to/notes

JIRA_BASE_URL=https://jira.example.com
JIRA_PAT=your-jira-pat
```

또는 token file 경로를 지정할 수도 있습니다.

```dotenv
CONFLUENCE_BASE_URL=https://confluence.example.com
CONFLUENCE_PAT_FILE=/path/to/confluence.token

JIRA_BASE_URL=https://jira.example.com
JIRA_PAT_FILE=/path/to/jira.token
```

설정 후에는 아래처럼 연결을 확인하면 됩니다.

```bash
./bin/conjira --env-file ./local/agent.env auth-check
./bin/conjira --env-file ./local/agent.env jira-auth-check
```

## 자주 쓰는 명령

Confluence 페이지 조회:

```bash
./bin/conjira --env-file ./local/agent.env get-page --page-id 123456 --expand body.storage,space,version
```

Confluence 페이지를 Markdown으로 export:

```bash
./bin/conjira --env-file ./local/agent.env export-page-md --page-id 123456 --output-dir "/path/to/work-folder"
```

Confluence 인라인 코멘트 스레드 export:

```bash
./bin/conjira --env-file ./local/agent.env export-inline-comments-md --page-id 123456 --status open --output-dir "/path/to/work-folder"
```

Confluence 페이지 생성 및 수정:

```bash
./bin/conjira --env-file ./local/agent.env create-page --allow-write --space-key DOCS --parent-id 100001 --title "CLI test page" --body-html "<p>Hello from conjira</p>"
./bin/conjira --env-file ./local/agent.env update-page --allow-write --page-id 100002 --append-html "<p>Updated by conjira</p>"
```

Markdown으로 Confluence 페이지 생성 및 수정:

```bash
./bin/conjira --env-file ./local/agent.env create-page --allow-write --space-key DOCS --parent-id 100001 --title "Markdown page" --body-markdown "# Demo\n\n- Item A"
./bin/conjira --env-file ./local/agent.env update-page --allow-write --page-id 100002 --append-markdown-file ./notes/update.md
```

Jira 검색과 이슈 조회:

```bash
./bin/conjira --env-file ./local/agent.env jira-search --jql 'project = DEMO ORDER BY created DESC' --limit 5
./bin/conjira --env-file ./local/agent.env jira-get-issue --issue-key DEMO-123
```

Jira 이슈 생성과 댓글 추가:

```bash
./bin/conjira --env-file ./local/agent.env jira-create-issue --allow-write --project-key DEMO --issue-type-name Task --summary "CLI issue test" --description "Created from conjira"
./bin/conjira --env-file ./local/agent.env jira-add-comment --allow-write --issue-key DEMO-123 --body "Comment from conjira"
```

## 설정 키

CLI 설정 우선순위는 다음과 같습니다.

1. `--base-url`, `--token` 같은 명시적 CLI 인자
2. 환경변수
3. `--env-file`로 불러온 값

Confluence 관련 설정:

- `CONFLUENCE_BASE_URL`
- `CONFLUENCE_PAT`
- `CONFLUENCE_PAT_FILE`
- `CONFLUENCE_PAT_KEYCHAIN_SERVICE`
- `CONFLUENCE_PAT_KEYCHAIN_ACCOUNT`
- `CONFLUENCE_TIMEOUT_SECONDS`
- `CONFLUENCE_ALLOWED_SPACE_KEYS`
- `CONFLUENCE_ALLOWED_PARENT_IDS`
- `CONFLUENCE_ALLOWED_PAGE_IDS`
- `CONFLUENCE_EXPORT_DEFAULT_DIR`
- `CONFLUENCE_EXPORT_STAGING_DIR`

Jira 관련 설정:

- `JIRA_BASE_URL`
- `JIRA_PAT`
- `JIRA_PAT_FILE`
- `JIRA_PAT_KEYCHAIN_SERVICE`
- `JIRA_PAT_KEYCHAIN_ACCOUNT`
- `JIRA_TIMEOUT_SECONDS`
- `JIRA_ALLOWED_PROJECT_KEYS`
- `JIRA_ALLOWED_ISSUE_KEYS`

## 안전 모델

이 CLI는 Confluence 페이지나 Jira 이슈 삭제 명령을 의도적으로 포함하지 않습니다.

모든 쓰기 명령은 `--allow-write`를 요구합니다. 즉 읽기 명령을 복사했다고 해서 실수로 변경이 일어나지 않습니다.

더 강한 안전장치가 필요하면 `local/agent.env`에 allowlist를 넣으면 됩니다. `CONFLUENCE_ALLOWED_*`나 `JIRA_ALLOWED_*`가 설정되어 있으면, PAT 자체 권한이 더 넓더라도 허용된 공간과 대상 밖으로는 쓰기가 차단됩니다.

## Export 전략

`local/`은 machine-local 설정, 임시 파일, staging 용도로만 쓰는 편이 좋습니다. 최종 Markdown 산출물은 보통 CLI 저장소 안이 아니라 실제 업무 폴더, 노트 저장소, 지식관리 폴더로 보내는 것이 자연스럽습니다.

권장 패턴은 `CONFLUENCE_EXPORT_DEFAULT_DIR`를 inbox나 업무 폴더로 두고, `CONFLUENCE_EXPORT_STAGING_DIR`은 `local/exports`로 두며, 최종 위치가 정해져 있으면 `--output-dir`를 쓰고, 잠깐 미리보기만 필요할 때만 `--staging-local`을 쓰는 방식입니다.

## Markdown import 관련 주의사항

Markdown 업로드는 Confluence storage HTML로의 best-effort 변환입니다. 일반적인 제목, 문단, 리스트, blockquote, fenced code block, 표, 링크, 이미지, 단순한 wiki 스타일 링크 정도에는 잘 맞지만, 복잡한 Confluence macro, 병합 셀, 아주 깊은 중첩 레이아웃까지 완벽하게 round-trip 하지는 않습니다.

`--body-file`과 `--append-file`은 storage HTML 파일용입니다. 입력 파일이 Markdown이면 `--body-markdown-file`이나 `--append-markdown-file`을 써야 CLI가 변환 후 업로드합니다.

## 에이전트 사용

다른 로컬 코딩 에이전트가 이 프로젝트를 사용해야 한다면 [docs/AGENT_USAGE.md](docs/AGENT_USAGE.md)를 참고하면 됩니다. 이 문서는 같은 머신에서 셸 명령을 실행할 수 있는 에이전트를 기준으로 작성되어 있습니다.

## 라이선스

이 저장소는 MIT License로 배포됩니다. 자세한 내용은 [LICENSE](LICENSE)를 참고하시면 됩니다.
