---
icon: lucide/list-checks
---

# Rule reference

## 1xx: Missing lazy declarations

| Code     | Meaning                                                            |
| -------- | ------------------------------------------------------------------ |
| `LZY101` | stdlib module should be listed in `__lazy_modules__`               |
| `LZY102` | third-party or local module should be listed in `__lazy_modules__` |

## 2xx: `__lazy_modules__` validation

| Code     | Meaning                                                         |
| -------- | --------------------------------------------------------------- |
| `LZY201` | `__lazy_modules__` is not sorted                                |
| `LZY202` | module listed in `__lazy_modules__` is never imported           |
| `LZY203` | module listed in `__lazy_modules__` is duplicated               |
| `LZY204` | `__lazy_modules__` is assigned after importing modules it names |
| `LZY205` | module listed in `__lazy_modules__` must be an absolute name    |

For `LZY201`, plain string entries sort alphabetically and relative
`f"{__spec__.parent}..."` entries go last, sorted among themselves. This matches
what a plain "sort lines" command in an editor produces.

## 3xx: Native `lazy` keyword (Python 3.15+)

| Code     | Meaning                                                            |
| -------- | ------------------------------------------------------------------ |
| `LZY301` | lazy import inside `suppress(ImportError)` is misleading           |
| `LZY302` | module declared lazy by both `lazy` keyword and `__lazy_modules__` |
| `LZY303` | module imported both eagerly and lazily                            |

## 4xx: Lazy import safety and semantics

| Code     | Meaning                                                             |
| -------- | ------------------------------------------------------------------- |
| `LZY401` | module is declared lazy but accessed at the top level               |
| `LZY402` | module is an enclosing package for this file and should not be lazy |
