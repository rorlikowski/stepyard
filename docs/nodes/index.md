# Built-in Nodes

13 nodes ship with Stepyard - no plugin install required. Quick examples:

```yaml
- id: ping
  uses: http.request
  with:
    url: https://api.example.com/healthz

- id: route
  uses: flow.route
  with:
    target: deploy_prod
    reason: tests passed
```

| Category | Nodes |
|---|---|
| Shell & System | `shell.run` |
| HTTP & Network | `http.request`, `http.download` |
| Files | `file.read`, `file.write`, `file.list` |
| Text | `text.template`, `text.replace` |
| AI / LLM | `llm.generate` |
| Human interaction | `human.input`, `human.approval` |
| Flow control | `flow.route`, `system.if` |

See the [full reference](builtin.md) for every parameter and tabbed example.
