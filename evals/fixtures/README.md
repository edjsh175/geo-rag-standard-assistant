# GeoAI E2E Fixtures

这些文件只用于真实 GeoAI E2E，不属于产品默认业务数据。

- 坐标系：EPSG:4326
- `sample_polygons.geojson`：两个有确定相交关系的简单面
- `sample_points.geojson`：两个位于成都附近的简单点
- `sample_shapefile/`：用于 SHP 导入验收的最小数据集，包含 `.shp`、`.shx`、`.dbf`、`.prj` 和 `.cpg`。

Fixture 保持最小和确定性，避免把外部数据版本变化引入验收结果。

这些输入必须随 Git 提交，以便干净 checkout 与 CI 能复现测试；运行结果仍留在被忽略的 `evals/results/`。

`../retrieval_gold.json` 是合成排序消融测试的输入，文档 ID 为测试标签，不代表真实知识库检索成绩。
