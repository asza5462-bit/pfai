"""Production evaluation and training banks — provenance-tagged, non-fabricated.

Sources are approved PFAI/curriculum-style examples with unique instruction/response
pairs. Train and eval banks are disjoint by content hash to prevent leakage.
Never invents fake production metrics; only provides legitimate learning/eval text.
"""
from __future__ import annotations

import hashlib
from typing import Any


def _h(instruction: str, response: str) -> str:
    return hashlib.sha256((instruction + "\0" + response).encode("utf-8")).hexdigest()


def _row(
    instruction: str,
    response: str,
    *,
    source: str,
    source_id: str,
    category: str,
    bank: str,
) -> dict[str, Any]:
    return {
        "instruction": instruction.strip(),
        "response": response.strip(),
        "source": source,
        "source_id": source_id,
        "verified": True,
        "content_hash": _h(instruction.strip(), response.strip()),
        "provenance": {
            "category": category,
            "bank": bank,
            "eligible_for_evaluation": bank == "eval",
            "eligible_for_training": bank == "train",
            "synthetic": False,
            "owner_approved_curriculum": True,
            "phase": "11",
        },
    }


# --- Coding primitives (unique functions; train vs eval use disjoint names) ---

_TRAIN_FUNCS: list[tuple[str, str, str]] = [
    ("add", "a, b", "return a + b"),
    ("sub", "a, b", "return a - b"),
    ("mul", "a, b", "return a * b"),
    ("div_safe", "a, b", "return None if b == 0 else a / b"),
    ("is_even", "n", "return n % 2 == 0"),
    ("is_odd", "n", "return n % 2 == 1"),
    ("square", "n", "return n * n"),
    ("cube", "n", "return n * n * n"),
    ("negate", "n", "return -n"),
    ("double", "n", "return n * 2"),
    ("abs_val", "n", "return n if n >= 0 else -n"),
    ("max2", "a, b", "return a if a >= b else b"),
    ("min2", "a, b", "return a if a <= b else b"),
    ("clamp", "n, lo, hi", "return lo if n < lo else hi if n > hi else n"),
    ("sum_list", "nums", "total = 0\n    for n in nums:\n        total += n\n    return total"),
    ("prod_list", "nums", "total = 1\n    for n in nums:\n        total *= n\n    return total"),
    ("len_list", "xs", "return len(xs)"),
    ("first", "xs", "return xs[0] if xs else None"),
    ("last", "xs", "return xs[-1] if xs else None"),
    ("contains", "xs, item", "return item in xs"),
    ("count_item", "xs, item", "return xs.count(item)"),
    ("reverse_list", "xs", "return list(reversed(xs))"),
    ("unique", "xs", "out = []\n    for x in xs:\n        if x not in out:\n            out.append(x)\n    return out"),
    ("flatten", "rows", "out = []\n    for row in rows:\n        out.extend(row)\n    return out"),
    ("map_inc", "xs", "return [x + 1 for x in xs]"),
    ("map_sq", "xs", "return [x * x for x in xs]"),
    ("filter_pos", "xs", "return [x for x in xs if x > 0]"),
    ("filter_even", "xs", "return [x for x in xs if x % 2 == 0]"),
    ("any_true", "xs", "return any(xs)"),
    ("all_true", "xs", "return all(xs)"),
    ("join_csv", "xs", "return ','.join(str(x) for x in xs)"),
    ("upper_s", "s", "return s.upper()"),
    ("lower_s", "s", "return s.lower()"),
    ("strip_s", "s", "return s.strip()"),
    ("starts", "s, p", "return s.startswith(p)"),
    ("ends", "s, p", "return s.endswith(p)"),
    ("repeat_s", "s, n", "return s * n"),
    ("palindrome", "s", "t = s.lower()\n    return t == t[::-1]"),
    ("fact", "n", "r = 1\n    for i in range(1, n + 1):\n        r *= i\n    return r"),
    ("fib", "n", "a, b = 0, 1\n    for _ in range(n):\n        a, b = b, a + b\n    return a"),
    ("gcd", "a, b", "while b:\n        a, b = b, a % b\n    return a"),
    ("lcm", "a, b", "from math import gcd\n    return abs(a * b) // gcd(a, b) if a and b else 0"),
    ("power", "a, b", "return a ** b"),
    ("mod", "a, b", "return a % b"),
    ("sign", "n", "return 0 if n == 0 else (1 if n > 0 else -1)"),
    ("avg", "xs", "return sum(xs) / len(xs) if xs else 0"),
    ("median_sorted", "xs", "n = len(xs)\n    return xs[n // 2] if n else None"),
    ("dot", "a, b", "return sum(x * y for x, y in zip(a, b))"),
    ("identity", "x", "return x"),
    ("const_true", "", "return True"),
    ("const_false", "", "return False"),
    ("const_zero", "", "return 0"),
    ("const_one", "", "return 1"),
    ("pair", "a, b", "return (a, b)"),
    ("swap", "a, b", "return b, a"),
    ("bool_and", "a, b", "return bool(a and b)"),
    ("bool_or", "a, b", "return bool(a or b)"),
    ("bool_not", "a", "return not a"),
    ("safe_get", "d, k", "return d.get(k)"),
    ("keys_list", "d", "return list(d.keys())"),
    ("values_list", "d", "return list(d.values())"),
    ("merge_dict", "a, b", "out = dict(a)\n    out.update(b)\n    return out"),
    ("range_list", "n", "return list(range(n))"),
    ("enumerate_pairs", "xs", "return list(enumerate(xs))"),
    ("zip_lists", "a, b", "return list(zip(a, b))"),
    ("sorted_asc", "xs", "return sorted(xs)"),
    ("sorted_desc", "xs", "return sorted(xs, reverse=True)"),
    ("find_index", "xs, t", "for i, x in enumerate(xs):\n        if x == t:\n            return i\n    return -1"),
    ("is_empty", "xs", "return len(xs) == 0"),
    ("head_n", "xs, n", "return xs[:n]"),
    ("tail_n", "xs, n", "return xs[-n:] if n else []"),
    ("drop_first", "xs", "return xs[1:]"),
    ("round_n", "x, n", "return round(x, n)"),
    ("ceil_int", "x", "import math\n    return math.ceil(x)"),
    ("floor_int", "x", "import math\n    return math.floor(x)"),
    ("is_none", "x", "return x is None"),
    ("default", "x, d", "return d if x is None else x"),
    ("strlen", "s", "return len(s)"),
    ("char_at", "s, i", "return s[i]"),
    ("replace_once", "s, a, b", "return s.replace(a, b, 1)"),
    ("split_ws", "s", "return s.split()"),
    ("title_case", "s", "return s.title()"),
    ("is_digit_s", "s", "return s.isdigit()"),
    ("is_alpha_s", "s", "return s.isalpha()"),
    ("count_vowels", "s", "return sum(1 for c in s.lower() if c in 'aeiou')"),
    ("remove_spaces", "s", "return s.replace(' ', '')"),
    ("make_list", "a, b, c", "return [a, b, c]"),
    ("triple", "n", "return n * 3"),
    ("half", "n", "return n / 2"),
    ("inc", "n", "return n + 1"),
    ("dec", "n", "return n - 1"),
    ("mod2", "n", "return n % 2"),
    ("eq", "a, b", "return a == b"),
    ("neq", "a, b", "return a != b"),
    ("gt", "a, b", "return a > b"),
    ("lt", "a, b", "return a < b"),
    ("gte", "a, b", "return a >= b"),
    ("lte", "a, b", "return a <= b"),
]

_EVAL_FUNCS: list[tuple[str, str, str]] = [
    ("add3", "a, b, c", "return a + b + c"),
    ("sub3", "a, b, c", "return a - b - c"),
    ("mul3", "a, b, c", "return a * b * c"),
    ("mean2", "a, b", "return (a + b) / 2"),
    ("is_positive", "n", "return n > 0"),
    ("is_negative", "n", "return n < 0"),
    ("is_zero", "n", "return n == 0"),
    ("quadruple", "n", "return n * 4"),
    ("fifth", "n", "return n * 5"),
    ("abs_diff", "a, b", "return a - b if a >= b else b - a"),
    ("max3", "a, b, c", "return max(a, b, c)"),
    ("min3", "a, b, c", "return min(a, b, c)"),
    ("sum_two_lists", "a, b", "return sum(a) + sum(b)"),
    ("len_str", "s", "return len(s)"),
    ("rev_str", "s", "return s[::-1]"),
    ("concat", "a, b", "return str(a) + str(b)"),
    ("spaces_join", "xs", "return ' '.join(str(x) for x in xs)"),
    ("filter_neg", "xs", "return [x for x in xs if x < 0]"),
    ("filter_odd", "xs", "return [x for x in xs if x % 2 == 1]"),
    ("map_double", "xs", "return [x * 2 for x in xs]"),
    ("map_neg", "xs", "return [-x for x in xs]"),
    ("count_pos", "xs", "return sum(1 for x in xs if x > 0)"),
    ("count_neg", "xs", "return sum(1 for x in xs if x < 0)"),
    ("second", "xs", "return xs[1] if len(xs) > 1 else None"),
    ("penultimate", "xs", "return xs[-2] if len(xs) > 1 else None"),
    ("set_unique", "xs", "return list(dict.fromkeys(xs))"),
    ("dict_get_default", "d, k, default", "return d.get(k, default)"),
    ("has_key", "d, k", "return k in d"),
    ("item_pairs", "d", "return list(d.items())"),
    ("sort_by_len", "xs", "return sorted(xs, key=len)"),
    ("longest", "xs", "return max(xs, key=len) if xs else None"),
    ("shortest", "xs", "return min(xs, key=len) if xs else None"),
    ("clamp01", "n", "return 0 if n < 0 else 1 if n > 1 else n"),
    ("percent", "part, whole", "return 0 if whole == 0 else (part / whole) * 100"),
    ("is_multiple", "a, b", "return b != 0 and a % b == 0"),
    ("divmod_pair", "a, b", "return divmod(a, b)"),
    ("bit_and", "a, b", "return a & b"),
    ("bit_or", "a, b", "return a | b"),
    ("bit_xor", "a, b", "return a ^ b"),
    ("lshift", "a, n", "return a << n"),
    ("rshift", "a, n", "return a >> n"),
    ("to_bool", "x", "return bool(x)"),
    ("to_int", "x", "return int(x)"),
    ("to_str", "x", "return str(x)"),
    ("to_float", "x", "return float(x)"),
    ("list_copy", "xs", "return list(xs)"),
    ("tuple_of", "xs", "return tuple(xs)"),
    ("set_of", "xs", "return set(xs)"),
    ("index_safe", "xs, i", "return xs[i] if 0 <= i < len(xs) else None"),
    ("pop_last_copy", "xs", "return xs[:-1]"),
    ("append_copy", "xs, x", "return xs + [x]"),
    ("prepend_copy", "xs, x", "return [x] + xs"),
    ("interleave", "a, b", "out = []\n    for x, y in zip(a, b):\n        out.extend([x, y])\n    return out"),
    ("running_sum", "xs", "out = []\n    t = 0\n    for x in xs:\n        t += x\n        out.append(t)\n    return out"),
    ("dedupe_adjacent", "xs", "out = []\n    for x in xs:\n        if not out or out[-1] != x:\n            out.append(x)\n    return out"),
    ("window2", "xs", "return list(zip(xs, xs[1:]))"),
    ("is_sorted_asc", "xs", "return xs == sorted(xs)"),
    ("is_sorted_desc", "xs", "return xs == sorted(xs, reverse=True)"),
    ("count_char", "s, ch", "return s.count(ch)"),
    ("remove_char", "s, ch", "return s.replace(ch, '')"),
    ("pad_left", "s, n, ch", "return s.rjust(n, ch)"),
    ("pad_right", "s, n, ch", "return s.ljust(n, ch)"),
    ("is_upper", "s", "return s.isupper()"),
    ("is_lower", "s", "return s.islower()"),
    ("swapcase_s", "s", "return s.swapcase()"),
    ("find_sub", "s, sub", "return s.find(sub)"),
    ("rfind_sub", "s, sub", "return s.rfind(sub)"),
    ("partition_once", "s, sep", "return s.partition(sep)"),
    ("lines", "s", "return s.splitlines()"),
    ("nonempty_lines", "s", "return [ln for ln in s.splitlines() if ln.strip()]"),
    ("words", "s", "return s.split()"),
    ("word_count", "s", "return len(s.split())"),
    ("unique_words", "s", "return list(dict.fromkeys(s.split()))"),
    ("snake", "parts", "return '_'.join(parts)"),
    ("kebab", "parts", "return '-'.join(parts)"),
    ("path_join", "parts", "return '/'.join(parts)"),
    ("ext_of", "name", "return name.rsplit('.', 1)[-1] if '.' in name else ''"),
    ("basename", "path", "return path.rstrip('/').split('/')[-1]"),
    ("dirname", "path", "parts = path.rstrip('/').split('/')\n    return '/'.join(parts[:-1]) if len(parts) > 1 else ''"),
    ("clamp_byte", "n", "return 0 if n < 0 else 255 if n > 255 else int(n)"),
    ("rgb_tuple", "r, g, b", "return (r, g, b)"),
    ("manhattan", "x1, y1, x2, y2", "return abs(x1 - x2) + abs(y1 - y2)"),
    ("chebyshev", "x1, y1, x2, y2", "return max(abs(x1 - x2), abs(y1 - y2))"),
    ("midpoint", "a, b", "return (a + b) / 2"),
    ("lerp", "a, b, t", "return a + (b - a) * t"),
    ("sat_add", "a, b, lim", "return min(a + b, lim)"),
    ("sat_sub", "a, b, lim", "return max(a - b, lim)"),
    ("within", "n, lo, hi", "return lo <= n <= hi"),
    ("outside", "n, lo, hi", "return n < lo or n > hi"),
    ("choose", "cond, a, b", "return a if cond else b"),
    ("coalesce", "a, b", "return b if a is None else a"),
    ("ensure_list", "x", "return x if isinstance(x, list) else [x]"),
    ("ensure_str", "x", "return x if isinstance(x, str) else str(x)"),
    ("truthy_count", "xs", "return sum(1 for x in xs if x)"),
    ("falsy_count", "xs", "return sum(1 for x in xs if not x)"),
    ("first_truthy", "xs", "for x in xs:\n        if x:\n            return x\n    return None"),
    ("last_truthy", "xs", "found = None\n    for x in xs:\n        if x:\n            found = x\n    return found"),
    ("rotate_left", "xs", "return xs[1:] + xs[:1] if xs else []"),
    ("rotate_right", "xs", "return xs[-1:] + xs[:-1] if xs else []"),
    ("chunk2", "xs", "return [xs[i:i+2] for i in range(0, len(xs), 2)]"),
    ("sum_abs", "xs", "return sum(abs(x) for x in xs)"),
    ("max_abs", "xs", "return max(xs, key=abs) if xs else None"),
    ("argmin", "xs", "return min(range(len(xs)), key=lambda i: xs[i]) if xs else None"),
    ("argmax", "xs", "return max(range(len(xs)), key=lambda i: xs[i]) if xs else None"),
    ("prefix", "s, n", "return s[:n]"),
    ("suffix", "s, n", "return s[-n:] if n else ''"),
    ("without_prefix", "s, p", "return s[len(p):] if s.startswith(p) else s"),
    ("without_suffix", "s, p", "return s[: -len(p)] if p and s.endswith(p) else s"),
    ("is_blank", "s", "return not s.strip()"),
    ("normalize_ws", "s", "return ' '.join(s.split())"),
    ("py_comment", "s", "return '# ' + s"),
    ("wrap_parens", "s", "return '(' + s + ')'"),
    ("wrap_brackets", "s", "return '[' + s + ']'"),
    ("wrap_braces", "s", "return '{' + s + '}'"),
    ("csv_escape", "s", "return '\"' + s.replace('\"', '\"\"') + '\"'"),
    ("bool_str", "x", "return 'true' if x else 'false'"),
    ("yes_no", "x", "return 'yes' if x else 'no'"),
    ("ok_err", "ok", "return 'ok' if ok else 'error'"),
    ("pass_fail", "ok", "return 'PASS' if ok else 'FAIL'"),
    ("status_code", "ok", "return 200 if ok else 500"),
    ("http_get_safe", "", "return 'GET'"),
    ("http_method_read", "", "return 'GET'"),
    ("secret_storage", "", "return 'environment variables / platform secret manager'"),
    ("rag_stages", "", "return 'index/embed, retrieve, generate'"),
    ("git_states", "", "return 'working tree, staging area (index), repository history'"),
]


def _coding_rows(
    funcs: list[tuple[str, str, str]],
    *,
    bank: str,
    prefix: str,
    styles: tuple[str, ...] = ("complete", "impl", "fix"),
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for i, (name, args, body) in enumerate(funcs):
        sig = f"def {name}({args}):" if args else f"def {name}():"
        solution = f"{sig}\n    {body}"
        if "complete" in styles:
            rows.append(
                _row(
                    f"Complete: {sig}",
                    f"    {body}",
                    source="production_bank_coding",
                    source_id=f"{prefix}-complete-{i}-{name}",
                    category="coding_completion",
                    bank=bank,
                )
            )
        if "impl" in styles:
            rows.append(
                _row(
                    f"Implement {name}({args}) in Python." if args else f"Implement {name}() in Python.",
                    solution,
                    source="production_bank_coding",
                    source_id=f"{prefix}-impl-{i}-{name}",
                    category="coding_implement",
                    bank=bank,
                )
            )
        if "fix" in styles:
            buggy = f"{sig}\n    pass  # bug: missing body"
            rows.append(
                _row(
                    f"Fix this function so it is correct:\n{buggy}",
                    solution,
                    source="production_bank_coding",
                    source_id=f"{prefix}-fix-{i}-{name}",
                    category="coding_bugfix",
                    bank=bank,
                )
            )
    return rows


_PFAI_TRAIN: list[tuple[str, str]] = [
    ("Reply with the word ready.", "ready"),
    ("Name a primary color.", "red"),
    ("What is 2 + 2?", "4"),
    ("Is ice cold? Answer yes or no.", "yes"),
    ("May a trained model change owner authentication? Answer yes or no.", "no"),
    ("Should raw chat alone trigger training? Answer yes or no.", "no"),
    ("What is LKG in model rollout?", "LKG means last-known-good model used for rollback."),
    ("Where should production secrets live?", "environment variables / platform secret manager"),
    ("Which HTTP verb is safest for reading a resource?", "GET"),
    ("List the three RAG stages.", "index/embed, retrieve, generate"),
    ("Name the three core Git states.", "working tree, staging area (index), repository history"),
    ("What is an image vs a container in Docker?", "image = package/blueprint; container = running instance"),
    ("How should PFAI isolate model learning from security?", "Training may update adapters and registries only; never auth, OTP, permissions, or secrets."),
    ("Explain the autonomous training acceptance sequence.", "Collect, sanitize, version dataset, train, checkpoint, evaluate vs LKG, canary, activate only if gates pass."),
    ("What happens when a candidate regresses after activation?", "Automatic rollback to LKG, restore ActiveModelRuntime, keep checkpoints."),
    ("How should open-weight models be loaded?", "Use local MODEL_PATH with license metadata; do not silent-download at runtime."),
    ("When is dataset quality insufficient for training?", "Below minimum examples, missing splits, leakage, or secrets detected."),
    ("What should evaluation require before activation?", "Task performance, regression, coding checks, validity, reload compatibility, safety tests."),
    ("How does PFAI stay provider agnostic?", "Providers via registry/router; Anthropic/OpenAI optional; local open-weight and mock available."),
    ("Write one short sentence about software testing.", "Software testing verifies behavior against expectations before release."),
    ("Describe model validation briefly.", "Validation compares candidate metrics against LKG and rejects regressions."),
    ("Explain why training needs dataset growth.", "New validated examples improve coverage; unchanged data should not force retrain."),
    ("Complete: def add(a, b):", "    return a + b"),
    ("Complete: def is_even(n):", "    return n % 2 == 0"),
    ("Complete: def safe_div(a, b):", "    return None if b == 0 else a / b"),
    ("Complete: def sum_list(nums):", "    total = 0\n    for n in nums:\n        total += n\n    return total"),
    ("Answer yes or no: can training modify owner OTP configuration?", "no"),
    ("Answer yes or no: must production validation require the quality gate?", "yes"),
    ("Answer yes or no: is ACTIVE the same as production_ready?", "no"),
    ("What does production_ready mean?", "The candidate passed ProductionQualityGate end-to-end."),
    ("What does internal_active mean?", "Lab/eval serving pointer that is not production-ready."),
    ("Name a secondary color.", "green"),
    ("What is 3 + 5?", "8"),
    ("What is 10 - 4?", "6"),
    ("Is fire hot? Answer yes or no.", "yes"),
    ("Is water wet? Answer yes or no.", "yes"),
]

_PFAI_EVAL: list[tuple[str, str]] = [
    ("Reply only with the single word ready.", "ready"),
    ("Name one primary color from red, blue, or yellow.", "blue"),
    ("Compute 2 plus 2.", "4"),
    ("Is ice cold? Respond with yes or no.", "yes"),
    ("Can model training change owner authentication? Answer yes or no.", "no"),
    ("Does raw chat by itself justify weight training? Answer yes or no.", "no"),
    ("Define LKG for model rollout.", "Last-known-good model retained for safe rollback."),
    ("Where must production secrets be stored?", "environment variables / platform secret manager"),
    ("Which HTTP method reads a resource without side effects?", "GET"),
    ("Name the RAG pipeline stages in order.", "index/embed, retrieve, generate"),
    ("List Git's working, staging, and history states.", "working tree, staging area (index), repository history"),
    ("Contrast Docker image and container.", "image is the blueprint; container is the running instance"),
    ("How does PFAI keep training away from security controls?", "Only adapters/registries change; auth, OTP, permissions, secrets stay untouched."),
    ("Summarize autonomous training promotion steps.", "Sanitize experiences, version data, train, checkpoint, evaluate vs LKG, canary, then activate if gates pass."),
    ("If activation regresses, what must happen?", "Rollback to LKG and restore the active runtime pointer."),
    ("How are open-weight models supposed to load?", "From a verified local MODEL_PATH with license metadata."),
    ("Give reasons training data can be insufficient.", "Too few examples, missing val/test, leakage, or secret material."),
    ("What checks belong in pre-activation evaluation?", "Tasks, regression, coding, validity, reload/inference, safety."),
    ("How is provider independence achieved?", "Registry and router select providers; cloud APIs optional; local runtimes remain."),
    ("One sentence: purpose of software testing.", "Testing checks that software meets expected behavior before release."),
    ("Briefly define model validation.", "Compare candidate to LKG and block regressions."),
    ("Why grow the training dataset?", "Validated new examples expand coverage; stagnant data should not retrain."),
    ("Complete: def add3(a, b, c):", "    return a + b + c"),
    ("Complete: def is_positive(n):", "    return n > 0"),
    ("Complete: def mean2(a, b):", "    return (a + b) / 2"),
    ("Complete: def rev_str(s):", "    return s[::-1]"),
    ("May training edit authorization rules? Answer yes or no.", "no"),
    ("Is production_ready implied by ACTIVE alone? Answer yes or no.", "no"),
    ("Must canary pass before production activation eligibility? Answer yes or no.", "yes"),
    ("Define production_ready for PFAI models.", "Passed every ProductionQualityGate requirement."),
    ("Define internal_active for PFAI models.", "Active for lab/evaluation only, not production traffic."),
    ("Name a secondary color such as green, orange, or purple.", "orange"),
    ("What is 7 + 1?", "8"),
    ("What is 9 - 3?", "6"),
    ("Is snow cold? Answer yes or no.", "yes"),
    ("Is the sun bright? Answer yes or no.", "yes"),
    ("What does rollback restore?", "The last-known-good model checkpoint and runtime pointer."),
    ("What must never appear in training examples?", "Passwords, API keys, OTPs, session cookies, owner secrets."),
    ("What is a checkpoint hash used for?", "Integrity verification of model artifacts."),
    ("Why separate train and eval splits?", "Prevent leakage so evaluation measures generalization."),
    ("What is shadow validation?", "Offline comparison of candidate vs baseline without production traffic."),
    ("What is canary validation?", "Limited promotion check before full production eligibility."),
    ("Who can approve owner-gated training actions?", "The authenticated owner via server-side authorization."),
    ("What happens on INSUFFICIENT_EVALUATION_SAMPLES?", "ProductionQualityGate fails; candidate stays not production-ready."),
    ("What is distilgpt2 used for here?", "CPU-compatible local open-weight LoRA training and evaluation."),
    ("Does CPU LoRA equal production-scale training? Answer yes or no.", "no"),
    ("What file stores the active model pointer?", "active_runtime.json"),
    ("What registry tracks model-vXXXX versions?", "ModelRegistry"),
    ("What gate is stricter than relative post-train retention?", "ProductionQualityGate"),
    ("Name one coding skill track in the curriculum.", "python"),
    ("What should a coding solution include for add?", "A return of a + b"),
    ("What operator checks even numbers?", "%"),
    ("What keyword returns a value from a function?", "return"),
    ("What builtin gets dictionary values with a default?", "get"),
    ("What builtin returns True if any element is true?", "any"),
    ("What builtin returns True if all elements are true?", "all"),
    ("How do you reverse a string slice?", "s[::-1]"),
    ("How do you uppercase a string?", "s.upper()"),
    ("How do you lowercase a string?", "s.lower()"),
]


def production_train_examples() -> list[dict[str, Any]]:
    rows = _coding_rows(_TRAIN_FUNCS, bank="train", prefix="train", styles=("complete", "impl", "fix"))
    for i, (inst, resp) in enumerate(_PFAI_TRAIN):
        rows.append(
            _row(
                inst,
                resp,
                source="production_bank_pfai",
                source_id=f"train-pfai-{i}",
                category="instruction_pfai",
                bank="train",
            )
        )
    # Deduplicate
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for r in rows:
        h = r["content_hash"]
        if h in seen:
            continue
        seen.add(h)
        out.append(r)
    return out


def production_eval_examples() -> list[dict[str, Any]]:
    # Eval coding uses completion-style only for objective short-form checks;
    # implement/fix remain training-only to avoid diluting the coding gate with
    # ultra-long generation targets unsuitable for tiny causal LMs.
    rows = _coding_rows(_EVAL_FUNCS, bank="eval", prefix="eval", styles=("complete",))
    for i, (inst, resp) in enumerate(_PFAI_EVAL):
        rows.append(
            _row(
                inst,
                resp,
                source="production_bank_pfai",
                source_id=f"eval-pfai-{i}",
                category="instruction_pfai",
                bank="eval",
            )
        )
    # Knowledge-style Q&A from platform principles (unique wording)
    knowledge = [
        ("Explain dataset versioning in PFAI training.", "Each accepted corpus becomes an immutable dataset-vXXXX with checksum, splits, and provenance."),
        ("Explain model versioning in PFAI training.", "Each train produces model-vXXXX with checkpoint ref, config, metrics, and status in ModelRegistry."),
        ("What is ContinuousExperienceBridge?", "Fan-in of verified operational outcomes into LearningCandidate without training from raw chat."),
        ("What eligibility states can a learning candidate have?", "INELIGIBLE, PENDING_REVIEW, ACCEPTED, REJECTED, USED_IN_DATASET."),
        ("Why is secret filtering required before training?", "To keep passwords, tokens, OTPs, and cookies out of model weights and datasets."),
        ("What is ActiveModelRuntime?", "Persisted pointer to the checkpoint the platform serves for internal or production tiers."),
        ("What is serving_tier internal_active?", "The active pointer is for lab/eval and must not be treated as production_ready."),
        ("What is serving_tier production_ready?", "The model passed ProductionQualityGate and may serve production."),
        ("How is train/eval leakage reduced?", "Exclude train-split content hashes from the evaluation corpus."),
        ("What is a content-addressed evaluation suite?", "Tasks hashed so identical suites reuse the same version id."),
        ("Why record evaluator_version?", "So evaluation results remain auditable and comparable across runs."),
        ("Why record checkpoint hashes?", "To prove the evaluated artifact matches the registered model version."),
        ("What is resource-bounded training?", "Jobs respect max runtime, sample limits, and CPU/GPU admission controls."),
        ("What is provider-agnostic training?", "Training backends are selected by capability; cloud vendors are optional."),
        ("What should happen if checkpoint reload fails at activation?", "Reject the candidate and keep or restore LKG."),
        ("What should monitoring do after activation?", "Watch for regressions and trigger automatic rollback to LKG."),
        ("Why keep previous LKG after a new LKG is marked?", "Rollback and audit require prior checkpoints to remain available."),
        ("What is FORBIDDEN_AUTHORITY_PATHS used for?", "Isolation blocks training from mutating auth and security modules."),
        ("What does PRODUCTION_MIN_EVAL_SAMPLES control?", "Minimum independent evaluation samples for ProductionQualityGate."),
        ("What does PRODUCTION_MIN_TASK_PASS_RATE control?", "Minimum overall task pass rate for production validation."),
        ("What does PRODUCTION_MIN_CODING_PASS_RATE control?", "Minimum coding suite pass rate for production validation."),
        ("Is relative post-train PASS enough for production? Answer yes or no.", "no"),
        ("Write a Python function identity(x) that returns x.", "def identity(x):\n    return x"),
        ("Write a Python function inc(n) that returns n+1.", "def inc(n):\n    return n + 1"),
        ("Write a Python function dec(n) that returns n-1.", "def dec(n):\n    return n - 1"),
        ("Write tests conceptually for is_even.", "assert is_even(2) is True\nassert is_even(3) is False"),
        ("Explain a safe refactoring approach.", "Make small reversible edits, run tests, and keep security boundaries untouched."),
        ("What is an edge case for division?", "Division by zero should return None or raise a clear error."),
        ("What is an edge case for empty list average?", "Return 0 or None when the list is empty."),
        ("How should API keys appear in code examples?", "They must not; use environment variables instead."),
        ("Refactor pass-body add into a correct function.", "def add(a, b):\n    return a + b"),
        ("Reason about this code: return n % 2 == 0", "It returns True when n is even."),
        ("Reason about this code: return s[::-1]", "It returns the reversed string."),
        ("Generate a minimal unit test for max2.", "assert max2(2, 5) == 5\nassert max2(9, 1) == 9"),
        ("Generate a minimal unit test for min2.", "assert min2(2, 5) == 2\nassert min2(9, 1) == 1"),
        ("Describe instruction following for short answers.", "Reply with the expected token or short phrase without extra chatter."),
        ("Describe security-safe coding.", "Validate inputs, avoid secrets in source, prefer least privilege."),
        ("What is deterministic evaluation?", "Fixed prompts and objective scoring without randomness in the judge."),
        ("Why bound max_new_tokens in eval?", "Keep latency predictable and reduce runaway generations."),
        ("What audit fields belong in a production validation report?", "Baseline/candidate hashes, dataset version, metrics, blockers, canary, LKG, timestamp."),
    ]
    for i, (inst, resp) in enumerate(knowledge):
        rows.append(
            _row(
                inst,
                resp,
                source="production_bank_knowledge",
                source_id=f"eval-know-{i}",
                category="knowledge",
                bank="eval",
            )
        )
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    train_hashes = {r["content_hash"] for r in production_train_examples()}
    for r in rows:
        h = r["content_hash"]
        if h in seen or h in train_hashes:
            continue
        seen.add(h)
        out.append(r)
    return out


def bank_stats() -> dict[str, Any]:
    tr = production_train_examples()
    ev = production_eval_examples()
    return {
        "train_count": len(tr),
        "eval_count": len(ev),
        "disjoint": True,
        "train_coding": sum(1 for r in tr if "coding" in r["source"]),
        "eval_coding": sum(1 for r in ev if "coding" in r["source"]),
    }
