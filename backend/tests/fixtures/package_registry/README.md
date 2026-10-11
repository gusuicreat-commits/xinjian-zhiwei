# 实验包序列化兼容夹具

`frozen_v1.json` 与 `serialization_v1.json` 是历史 v1 包格式的哈希稳定性快照；保留 HEAD 的原始内容与 DHT11 key，不从当前 SHT31 包重新生成。`test_package_registry.py` 继续用这些冻结材料验证旧格式重建、规范哈希和缺省字段兼容性。这里的 DHT11 字样仅代表历史兼容测试数据，不注册或加载已删除的实验包。
