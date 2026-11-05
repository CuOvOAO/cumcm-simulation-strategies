# Local-only reproduction; never invokes run_q4_official.py.
$ErrorActionPreference = 'Stop'
$q4Root = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $q4Root
$q4Python = Join-Path $q4Root '..\..\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $q4Python)) { $q4Python = 'python' }
& $q4Python -X utf8 -m unittest -v
if ($LASTEXITCODE -ne 0) { throw 'Root tests failed' }
& $q4Python -X utf8 -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw 'Inherited tests failed' }
& $q4Python -X utf8 experiments/run_q4.py --generate development --count 48 --variants Q4_BATCH Q4_IMMEDIATE Q4_JOINT Q4_JOINT_VIEWS Q4_PURSUIT Q4_FORK_BATCH Q4_FORK_JOINT Q4_FORK_VIEWS --jobs 4 --out results/q4_reproduction_development
if ($LASTEXITCODE -ne 0) { throw 'Development run failed' }
& $q4Python -X utf8 experiments/validate_q4.py --count 128 --jobs 4 --out results/q4_reproduction_validation
if ($LASTEXITCODE -ne 0) { throw 'Validation run failed' }
& $q4Python -X utf8 experiments/run_q4.py --generate fixed_q4 --cases cases_extra/q4/fixed_q4 --variants Q4_FORK_VIEWS --jobs 4 --out results/q4_reproduction_fixed
if ($LASTEXITCODE -ne 0) { throw 'Fixed run failed' }
& $q4Python -X utf8 -c "from experiments.run_q4 import generate; generate('stress',64)"
if ($LASTEXITCODE -ne 0) { throw 'Stress generation failed' }
foreach ($q4Mode in @('positive','negative','checker','smooth')) {
    & $q4Python -X utf8 experiments/run_q4.py --cases cases_extra/q4/stress --variants Q4_FORK_VIEWS --error-mode $q4Mode --jobs 4 --out "results/q4_reproduction_stress_$q4Mode"
    if ($LASTEXITCODE -ne 0) { throw "Stress run failed: $q4Mode" }
}
& $q4Python -X utf8 experiments/audit_q4.py results/q4_reproduction_development results/q4_reproduction_validation results/q4_reproduction_fixed results/q4_reproduction_stress_positive results/q4_reproduction_stress_negative results/q4_reproduction_stress_checker results/q4_reproduction_stress_smooth --output results/q4_reproduction_audit.json
if ($LASTEXITCODE -ne 0) { throw 'Certificate audit failed' }
