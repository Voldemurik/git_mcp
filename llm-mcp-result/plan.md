## План
1. Прочитать данные через собственный MCP.
2. Прочитать метрику через Filesystem MCP.
3. Очистить рекомендации: убрать просмотренные (history), дубликаты, отсутствующие в каталоге.
4. Считать Recall@K по формуле |top-K ∩ relevant|/|relevant|.
5. Build: clean_recommendations + save_result.
6. Review: host-проверки.
