#!/usr/bin/env bash
# banana で sudo が要るのはこれだけ。ppc-research/rtl の検証（yosys / iverilog）に使う。
# シミュレータと解析だけなら不要。Go は setup-user.sh が sudo なしで 1.26.1 にする。
#
#   sudo bash setup-root.sh
set -euo pipefail
apt-get update
apt-get install -y yosys iverilog
