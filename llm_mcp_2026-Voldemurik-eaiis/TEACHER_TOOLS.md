# Какие инструменты получает студент в каждом варианте

Для каждого варианта выдаются три **фиксированных** инструмента собственного MCP.
Функция чтения и `save_result()` уже реализованы в заготовке; предметную функцию студент пишет самостоятельно.

| Вариант | Тема | Чтение | Предметная обработка | Сохранение |
|---|---|---|---|---|
| K01 | NumPy: неправильный broadcasting скидок | `get_price_data()` | `calculate_discounted_prices()` | `save_result()` |
| K02 | NumPy: переполнение при суммировании сенсоров | `get_measurements()` | `verify_thresholds()` | `save_result()` |
| K03 | NumPy: воспроизводимая случайная выборка | `get_subjects()` | `check_split()` | `save_result()` |
| K04 | pandas: опасное many-to-many объединение | `get_join_sources()` | `inspect_join_keys()` | `save_result()` |
| K05 | pandas: часовые пояса и границы месяца | `get_events()` | `calculate_local_months()` | `save_result()` |
| K06 | pandas: пропуски и денежные типы | `get_sales()` | `audit_missing_values()` | `save_result()` |
| K07 | scikit-learn: групповая кросс-валидация | `get_samples()` | `verify_group_split()` | `save_result()` |
| K08 | scikit-learn: OneHotEncoder и неизвестные категории | `get_categories()` | `validate_encoder_settings()` | `save_result()` |
| K09 | scikit-learn: утечка при стандартизации | `read_scaler_case()` | `compare_fit_scope()` | `save_result()` |
| K10 | Hugging Face: padding, truncation и attention_mask | `read_preprocessing_case()` | `check_tokenizer_config()` | `save_result()` |
| K11 | CLIP: zero-shot классификация с несколькими формулировками | `read_scores()` | `rank_labels()` | `save_result()` |
| K12 | CLIP: выбор prompt и оценка неоднозначности | `get_prompt_scores()` | `compare_predictions()` | `save_result()` |
| G01 | Git: найти регрессию порога для классификатора | `get_test_cases()` | `verify_threshold()` | `save_result()` |
| G02 | Git: регрессия в нормализации токенов | `get_examples()` | `check_normalization()` | `save_result()` |
| G03 | Git: некорректное косинусное сходство | `get_vectors()` | `test_cosine()` | `save_result()` |
| G04 | Git: нарушено соответствие признаков и меток | `get_pairs()` | `check_alignment()` | `save_result()` |
| G05 | GitVerse: аудит CI проекта прикладного ИИ | `get_ci_snapshot()` | `evaluate_required_checks()` | `save_result()` |
| G06 | GitVerse: сравнение кода и release notes | `get_changes()` | `compare_release_notes()` | `save_result()` |
| P01 | Filesystem: дрейф схемы ML-датасета | `get_schema()` | `detect_schema_diff()` | `save_result()` |
| P02 | Filesystem: утечка времени в прогнозировании | `read_feature_catalog()` | `detect_time_leakage()` | `save_result()` |
| P03 | Filesystem: аудит экспериментов ML | `get_runs()` | `group_comparable_runs()` | `save_result()` |
| P04 | Filesystem: диагностика метрик рекомендательной системы | `get_user_data()` | `clean_recommendations()` | `save_result()` |
| P05 | Filesystem: конфликт таксономии NLP-разметки | `get_annotations()` | `reconcile_labels()` | `save_result()` |
| P06 | Filesystem: аудит zero-shot оценок без модели | `read_scores()` | `compare_score_sets()` | `save_result()` |

**Примечание:** это не эталонные решения. В каталоге нет ответов к предметным задачам.
