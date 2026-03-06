@echo off
:: 环境中已有 numpy，不需要重复安装
python modeling.py --epochs 1000 --area_size 200 --p_tx 23