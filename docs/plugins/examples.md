# Real-world Plugin Examples

Copy-paste-ready patterns for common integration scenarios.

---

## AI agent - OpenAI

A node that calls the OpenAI Chat API and returns the model's response.

=== "Plugin (Python)"

    ```python title="src/stepyard_plugin_openai/nodes.py"
    import os
    import httpx
    from stepyard.sdk import node, NodeResult
    from stepyard.core.errors import TransientError


    @node(name="openai.chat")
    async def chat(
        prompt: str,
        model: str = "gpt-4o",
        system: str = "You are a helpful assistant.",
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> NodeResult:
        api_key = os.environ["OPENAI_API_KEY"]

        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "model": model,
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": prompt},
                        ],
                    },
                    timeout=60,
                )
            except httpx.TimeoutException as exc:
                raise TransientError("OpenAI request timed out") from exc

        resp.raise_for_status()
        data = resp.json()
        text = data["choices"][0]["message"]["content"]

        return NodeResult(
            status="success",
            output={
                "text": text,
                "tokens": data["usage"]["total_tokens"],
                "model": data["model"],
            },
        )
    ```

=== "Flow (YAML)"

    ```yaml title="flows/pr_review.yaml"
    name: pr_review
    steps:
      - id: diff
        uses: shell.run
        with:
          command: git diff origin/main...HEAD

      - id: review
        uses: openai.chat
        with:
          model: gpt-4o
          system: You are a senior engineer. Be concise and actionable.
          prompt: |
            Review this diff for bugs, security issues, and style problems.
            Reply with "LGTM" if everything looks fine.

            ${{ steps.diff.output.stdout }}

      - id: post_comment
        if: ${{ steps.review.output.text != "LGTM" }}
        uses: http.request
        with:
          url: ${{ env.GITHUB_PR_COMMENT_URL }}
          method: POST
          json_body:
            body: ${{ steps.review.output.text }}
    ```

---

## Database - PostgreSQL query

=== "Plugin (Python)"

    ```python title="src/stepyard_plugin_postgres/nodes.py"
    from typing import Any
    import psycopg2
    import psycopg2.extras
    from stepyard.sdk import node, NodeResult
    from stepyard.core.errors import TransientError, NodeExecutionError


    @node(name="postgres.query")
    def query(
        connection_string: str,
        sql: str,
        params: list[Any] | None = None,
    ) -> NodeResult:
        try:
            with psycopg2.connect(connection_string) as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(sql, params or [])
                    conn.commit()
                    try:
                        rows = [dict(row) for row in cur.fetchall()]
                    except psycopg2.ProgrammingError:
                        rows = []  # INSERT/UPDATE/DELETE - no rows to fetch

            return NodeResult(
                status="success",
                output={"rows": rows, "count": len(rows)},
            )
        except psycopg2.OperationalError as exc:
            raise TransientError(f"DB connection failed: {exc}") from exc
        except psycopg2.Error as exc:
            raise NodeExecutionError(f"Query error: {exc}") from exc
    ```

=== "Flow (YAML)"

    ```yaml title="flows/report_active_users.yaml"
    name: report_active_users
    trigger:
      uses: cron
      with:
        schedule: "0 9 * * 1"   # every Monday at 09:00

    steps:
      - id: fetch_users
        uses: postgres.query
        with:
          connection_string: ${{ env.DATABASE_URL }}
          sql: |
            SELECT id, email, last_login
            FROM users
            WHERE last_login > NOW() - INTERVAL '7 days'
            ORDER BY last_login DESC

      - id: report
        uses: llm.generate
        with:
          model: gpt-4o-mini
          prompt: |
            Summarise this weekly active users report in 3 bullet points.
            ${{ steps.fetch_users.output.rows }}

      - id: send_report
        uses: http.request
        with:
          url: ${{ env.SLACK_WEBHOOK }}
          method: POST
          json_body:
            text: "📊 Weekly active users (${{ steps.fetch_users.output.count }} users):\n${{ steps.report.output.output }}"
    ```

---

## ETL pipeline - transform and load

=== "Plugin (Python)"

    ```python title="src/stepyard_plugin_etl/nodes.py"
    from typing import Any
    from stepyard.sdk import node, NodeResult


    @node(name="etl.filter")
    def filter_records(
        records: list[dict[str, Any]],
        field: str,
        value: Any,
        operator: str = "eq",
    ) -> NodeResult:
        """Filter a list of dicts."""
        ops = {
            "eq": lambda r: r.get(field) == value,
            "neq": lambda r: r.get(field) != value,
            "gt": lambda r: r.get(field, 0) > value,
            "lt": lambda r: r.get(field, 0) < value,
            "contains": lambda r: value in str(r.get(field, "")),
        }
        if operator not in ops:
            raise ValueError(f"Unknown operator: {operator}. Use: {', '.join(ops)}")

        filtered = [r for r in records if ops[operator](r)]
        return NodeResult(
            status="success",
            output={"records": filtered, "count": len(filtered), "dropped": len(records) - len(filtered)},
        )


    @node(name="etl.map")
    def map_fields(
        records: list[dict[str, Any]],
        mapping: dict[str, str],
    ) -> NodeResult:
        """Rename or extract fields."""
        result = [{new: r.get(old) for new, old in mapping.items()} for r in records]
        return NodeResult(status="success", output={"records": result, "count": len(result)})
    ```

=== "Flow (YAML)"

    ```yaml title="flows/sync_users.yaml"
    name: sync_users

    steps:
      - id: fetch
        uses: http.request
        with:
          url: https://api.source-system.com/users
          headers:
            Authorization: Bearer ${{ env.SOURCE_API_TOKEN }}

      - id: filter_active
        uses: etl.filter
        with:
          records: ${{ steps.fetch.output.body.users }}
          field: is_active
          value: true

      - id: map_fields
        uses: etl.map
        with:
          records: ${{ steps.filter_active.output.records }}
          mapping:
            id: user_id
            email: email_address
            name: display_name

      - id: upload
        uses: http.request
        with:
          url: https://api.target-system.com/import/users
          method: POST
          headers:
            Authorization: Bearer ${{ env.TARGET_API_TOKEN }}
          json_body:
            users: ${{ steps.map_fields.output.records }}

      - id: log
        uses: shell.run
        with:
          command: |
            echo "Synced ${{ steps.map_fields.output.count }} users. \
            Filtered out ${{ steps.filter_active.output.dropped }} inactive."
    ```

---

## AWS S3 - upload and sign URL

=== "Plugin (Python)"

    ```python title="src/stepyard_plugin_aws/nodes.py"
    import boto3
    from stepyard.sdk import node, NodeResult
    from stepyard.core.errors import TransientError
    from botocore.exceptions import BotoCoreError, ClientError


    @node(name="aws.s3_upload")
    def s3_upload(
        bucket: str,
        key: str,
        local_path: str,
        region: str = "us-east-1",
        content_type: str = "application/octet-stream",
    ) -> NodeResult:
        try:
            s3 = boto3.client("s3", region_name=region)
            s3.upload_file(
                local_path, bucket, key,
                ExtraArgs={"ContentType": content_type},
            )
            url = f"https://{bucket}.s3.{region}.amazonaws.com/{key}"
            return NodeResult(status="success", output={"url": url, "key": key, "bucket": bucket})
        except (BotoCoreError, ClientError) as exc:
            raise TransientError(f"S3 upload failed: {exc}") from exc


    @node(name="aws.s3_presign")
    def s3_presign(bucket: str, key: str, expires_in: int = 3600) -> NodeResult:
        s3 = boto3.client("s3")
        url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=expires_in,
        )
        return NodeResult(status="success", output={"url": url, "expires_in": expires_in})
    ```

=== "Flow (YAML)"

    ```yaml title="flows/release_artifact.yaml"
    name: release_artifact

    steps:
      - id: build
        uses: shell.run
        with:
          command: python -m build --outdir dist/

      - id: upload
        uses: aws.s3_upload
        retry:
          attempts: 3
          initial_delay: 5
        with:
          bucket: ${{ env.ARTIFACT_BUCKET }}
          key: releases/${{ env.VERSION }}/dist.tar.gz
          local_path: dist/

      - id: presign
        uses: aws.s3_presign
        with:
          bucket: ${{ env.ARTIFACT_BUCKET }}
          key: releases/${{ env.VERSION }}/dist.tar.gz
          expires_in: 86400

      - id: notify
        uses: http.request
        with:
          url: ${{ env.SLACK_WEBHOOK }}
          method: POST
          json_body:
            text: "📦 Release ${{ env.VERSION }} uploaded.\nDownload: ${{ steps.presign.output.url }}"
    ```

---

## Slack notifications

=== "Plugin (Python)"

    ```python title="src/stepyard_plugin_slack/nodes.py"
    import httpx
    from stepyard.sdk import node, NodeResult
    from stepyard.core.errors import TransientError


    @node(name="slack.post")
    async def post_message(
        webhook_url: str,
        text: str,
        username: str = "Stepyard",
        icon_emoji: str = ":robot_face:",
        blocks: list | None = None,
    ) -> NodeResult:
        payload = {"text": text, "username": username, "icon_emoji": icon_emoji}
        if blocks:
            payload["blocks"] = blocks

        async with httpx.AsyncClient() as client:
            resp = await client.post(webhook_url, json=payload, timeout=10)
            if resp.text != "ok":
                raise TransientError(f"Slack returned: {resp.text}")

        return NodeResult(status="success", output={"sent": True})
    ```

=== "Flow (YAML)"

    ```yaml title="flows/deploy.yaml"
    name: deploy

    steps:
      - id: deploy
        uses: shell.run
        continue_on_error: true
        with:
          command: kubectl apply -f k8s/

      - id: notify_success
        if: ${{ steps.deploy.output.code == 0 }}
        uses: slack.post
        with:
          webhook_url: ${{ env.SLACK_WEBHOOK }}
          text: "✅ *Deploy succeeded* on `${{ env.HOSTNAME }}`"

      - id: notify_failure
        if: ${{ steps.deploy.output.code != 0 }}
        uses: slack.post
        with:
          webhook_url: ${{ env.SLACK_WEBHOOK }}
          text: |
            🚨 *Deploy failed* on `${{ env.HOSTNAME }}`
            ```${{ steps.deploy.output.stdout }}```
    ```
