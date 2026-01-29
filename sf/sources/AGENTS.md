# sf/sources/ — External Demand Adapters

Converts external signals into WorkOrder params for the ShopFloor queue.

## Pattern

```
SourceAdapter (ABC)
  ├── parse_event(payload) → SourceEvent | None
  └── to_work_order_params(event) → dict
```

## Adapters

| Adapter | Endpoint | Trigger |
|---------|----------|---------|
| `GitHubSourceAdapter` | `POST /webhook/github` | Issue opened/reopened, PR opened |
| `JiraSourceAdapter` | `POST /webhook/jira` | Issue created/updated |
| `AlertSourceAdapter` | `POST /webhook/alert` | Prometheus AlertManager firing |
| `CLISourceAdapter` | direct | `--workorder-type` CLI input |

## Server Wiring

`parse_event()` → `to_work_order_params()` → `WorkOrder(index=_next_index(), **params)` → `webhook_queue.enqueue(wo)`.
