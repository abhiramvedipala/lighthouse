#!/usr/bin/env bash
# Download public benchmark data into data/ (gitignored, never committed).
#  - Loghub 2k structured samples with ground-truth templates (logpai/loghub, research use,
#    cite the repo and "Loghub: A Large Collection of System Log Datasets", Zhu et al., ISSRE 2023)
#  - Numenta Anomaly Benchmark series and labels (NAB)
set -euo pipefail
cd "$(dirname "$0")/.."
LOGHUB=https://raw.githubusercontent.com/logpai/loghub/master
NAB=https://raw.githubusercontent.com/numenta/NAB/master
mkdir -p data/loghub data/nab

get() { # url dest min_bytes
  if [ -s "$2" ] && [ "$(wc -c < "$2")" -ge "$3" ]; then echo "cached $2"; return; fi
  curl -fsSL --retry 3 "$1" -o "$2"
  size=$(wc -c < "$2")
  [ "$size" -ge "$3" ] || { echo "FAIL: $2 is only $size bytes"; rm -f "$2"; exit 1; }
  echo "got $2 ($size bytes)"
}

for ds in HDFS BGL OpenStack Apache; do
  get "$LOGHUB/$ds/${ds}_2k.log_structured.csv" "data/loghub/${ds}_2k.log_structured.csv" 100000
done

get "$NAB/data/realKnownCause/machine_temperature_system_failure.csv" data/nab/machine_temperature_system_failure.csv 100000
for f in ec2_cpu_utilization_825cc2 rds_cpu_utilization_cc0c53 elb_request_count_8c0756; do
  get "$NAB/data/realAWSCloudwatch/$f.csv" "data/nab/$f.csv" 50000
done
get "$NAB/labels/combined_windows.json" data/nab/combined_windows.json 1000
echo "data ready in data/"
