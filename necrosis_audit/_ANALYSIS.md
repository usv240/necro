# Necrosis audit — accuracy analysis

## demo_gitaly  (demo)
- findings: 9 | summary: excise=1 biopsy=8 intact=0
- file: symbols=0 | TLD symbols=0 | excise-safety-violations=0 | spec-as-caller=0 | duplicates=0
- caller_count_reliable field present on 9/9 findings (0 = pre-fix cached data; >0 = fixed pipeline)
- excise_now: 1 aged>=180d (ok), 0 young (suspicious)
- no issues flagged ✓

## demo_gitlab-runner  (demo)
- findings: 11 | summary: excise=4 biopsy=7 intact=0
- file: symbols=0 | TLD symbols=0 | excise-safety-violations=0 | spec-as-caller=0 | duplicates=0
- caller_count_reliable field present on 11/11 findings (0 = pre-fix cached data; >0 = fixed pipeline)
- excise_now: 4 aged>=180d (ok), 0 young (suspicious)
- no issues flagged ✓

## demo_gitlab-shell  (demo)
- findings: 9 | summary: excise=0 biopsy=8 intact=1
- file: symbols=0 | TLD symbols=0 | excise-safety-violations=0 | spec-as-caller=0 | duplicates=0
- caller_count_reliable field present on 9/9 findings (0 = pre-fix cached data; >0 = fixed pipeline)
- excise_now: 0 aged>=180d (ok), 0 young (suspicious)
- no issues flagged ✓

## demo_gitlab  (demo)
- findings: 10 | summary: excise=1 biopsy=9 intact=0
- file: symbols=0 | TLD symbols=0 | excise-safety-violations=0 | spec-as-caller=0 | duplicates=0
- caller_count_reliable field present on 10/10 findings (0 = pre-fix cached data; >0 = fixed pipeline)
- excise_now: 1 aged>=180d (ok), 0 young (suspicious)
- no issues flagged ✓

## live_gitaly  (live)
- findings: 9 | summary: excise=1 biopsy=8 intact=0
- file: symbols=0 | TLD symbols=0 | excise-safety-violations=0 | spec-as-caller=0 | duplicates=0
- caller_count_reliable field present on 9/9 findings (0 = pre-fix cached data; >0 = fixed pipeline)
- excise_now: 1 aged>=180d (ok), 0 young (suspicious)
- no issues flagged ✓

## live_gitlab-runner  (live)
- findings: 11 | summary: excise=4 biopsy=7 intact=0
- file: symbols=0 | TLD symbols=0 | excise-safety-violations=0 | spec-as-caller=0 | duplicates=0
- caller_count_reliable field present on 11/11 findings (0 = pre-fix cached data; >0 = fixed pipeline)
- excise_now: 4 aged>=180d (ok), 0 young (suspicious)
- no issues flagged ✓

## live_gitlab-shell  (live)
- findings: 9 | summary: excise=0 biopsy=8 intact=1
- file: symbols=0 | TLD symbols=0 | excise-safety-violations=0 | spec-as-caller=0 | duplicates=0
- caller_count_reliable field present on 9/9 findings (0 = pre-fix cached data; >0 = fixed pipeline)
- excise_now: 0 aged>=180d (ok), 0 young (suspicious)
- no issues flagged ✓

## live_gitlab  (live)
- findings: 10 | summary: excise=1 biopsy=9 intact=0
- file: symbols=0 | TLD symbols=0 | excise-safety-violations=0 | spec-as-caller=0 | duplicates=0
- caller_count_reliable field present on 10/10 findings (0 = pre-fix cached data; >0 = fixed pipeline)
- excise_now: 1 aged>=180d (ok), 0 young (suspicious)
- no issues flagged ✓

## TOTALS across all captured files
- file: symbols: 0
- TLD symbols: 0
- excise_now safety violations: 0
- spec/test counted as caller: 0
- duplicates: 0