Заключение: host-проверки подтверждают case_id=P04, top-3=[B,C], Recall@3=0.5, отчёт корректный. Результат готов к сдаче; ограничение: метрика посчитана на небольшом файле без обучения.

## Расход токенов GigaChat (собственный учёт)

```json
{
  "requests_total": 6,
  "requests_without_usage": 0,
  "phases": {
    "plan": {
      "requests": 3,
      "prompt_tokens": 300,
      "completion_tokens": 120,
      "total_tokens": 420,
      "precached_prompt_tokens": 30
    },
    "build": {
      "requests": 3,
      "prompt_tokens": 300,
      "completion_tokens": 120,
      "total_tokens": 420,
      "precached_prompt_tokens": 30
    },
    "review": {
      "requests": 0,
      "prompt_tokens": 0,
      "completion_tokens": 0,
      "total_tokens": 0,
      "precached_prompt_tokens": 0
    }
  },
  "totals": {
    "prompt_tokens": 600,
    "completion_tokens": 240,
    "total_tokens": 840,
    "precached_prompt_tokens": 60
  }
}
```
