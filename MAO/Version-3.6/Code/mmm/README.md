2023.11.7-2023.11.10 | dyf
经验持久化pipeline：
1. 利用`mmm/prep/dataset_dir.py`脚本中`get_filenameList`获取当前category下所有的主软件(文件夹名称中不带NewFeature)路径及文件名称。
2. 启动`mmm.py`，将该类别下所有软件制造经验持久化，储存在'MemoryCards_{category}.json'文件中；所有的日志文件储存在`{category}`文件夹下,名称为`mmm_{软件文件名}`
3. 在所有的category下经验持久化运行结束后，每个'MemoryCards_{category}.json'中应有30条`MemoryPiece`，将前20个作为训练集，21-25个作为验证集，26-30个作为测试集。
运行`mmm/prep/dataset_split.py`下的`train_split`，将所有category下的前20条`MemoryPiece`合并到同一个json文件中。
4. 启动`mmm/prep/experience_filter.py`，利用设置经验`valuegain`阈值为0.9，对于训练集进行经验过滤，得到`MemoryCards_filtered_0.9.json`(为方便Chatdev运行，此文件现更名为`MemoryCards.json`)

验证集实验pipeline：
1. 在主文件夹下的`exp_run.py`中，修改`get_task()`参数为任一category，启动`exp_run.py`即可。 
