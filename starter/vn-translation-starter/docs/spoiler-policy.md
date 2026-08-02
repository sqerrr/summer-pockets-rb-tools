# Spoiler Policy

Raw source and private constraints are internal inputs. Generated work packages
may include source text because they remain under ignored `build/`.

User-visible output may include:

- translated text the user requested;
- counts and statuses;
- local non-spoiler quality notes;
- safe rules such as "keep the subject ambiguous";
- facts already revealed by the user's progress.

User-visible output must not include:

- private reasons or `reveal_after` values;
- future roles, identities, relationships, or outcomes;
- future-scene references used to justify a translation;
- raw source dumps, question text, or speaker lists from unseen content.

Only `safe_rules` from `private/constraints.jsonl` may enter context packages.
`brief`, `stats`, and `questions` intentionally print counts only.
