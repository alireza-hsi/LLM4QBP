<<<<<<< HEAD
# li jia hao
# 时间：2023/11/8 20:46
import openai
from openai import OpenAI

client = OpenAI(
    api_key='sk-R0heaABPw3Fux159D2E60cDd4c3245A596B40201155a6a06',
    base_url="https://sailaoda.cn/v1",
)
import pandas as pd
from sklearn.cluster import KMeans
import os
import sys
from utils import get_easyDict_from_filepath
import re

sys.path.append(os.path.join(os.getcwd(),"mmm"))
cfg = get_easyDict_from_filepath("./mmm/config.yaml")

commentlist = []
comment_embedding = []

#获得comment list



def get_commentlist(directory):
    logdir = [filename for filename in os.listdir(directory) if filename.endswith(".log")]
    if len(logdir) > 0:
        log_filename = logdir[0]
        print("log_filename:", log_filename)
    else:
        raise Exception("No log file found in {}".format(directory))

    content = open(os.path.join(directory, log_filename), "r", encoding='UTF-8').read()

    utterances = []
    regex = r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \w+)\] ([.\s\S\n\r\d\D\t]*?)(?=\n\[\d|$)"
    matches = re.finditer(regex, content, re.DOTALL)

    for match in matches:
        group1 = match.group(1)
        group2 = match.group(2)
        utterances.append("[{}] {}".format(group1, group2))

    utterances = [utterance for utterance in utterances if
                  "flask app.py" not in utterance and "OpenAI_Usage_Info" not in utterance]

    index = [i for i, utterance in enumerate(utterances) if
             "Programmer<->Chief Technology Officer on : EnvironmentDoc" in utterance]

    utterances = utterances[:index[0] - 1]

    utterances_comment = [utterance for utterance in utterances if
                          "Code Reviewer: **[Start Chat]**" in utterance and "EnvironmentDoc" not in utterance and "TestErrorSummary" not in utterance]

    for utterance in utterances_comment:
        pattern = r"Comments on Codes:(.*?)In the software, each file must strictly follow a markdown code block format"
        match = re.search(pattern, utterance, re.DOTALL)

        if match:
            extracted_text = match.group(1).strip()
            commentlist.append(extracted_text)
            print("extracted_comment")

directories = os.listdir(r'./full')
for directory in directories:
    if "_NewFeature_" not in directory:
        get_commentlist(os.path.join(r'./full', directory))


#将保存comment
df_comment = pd.DataFrame(commentlist, columns = ['comment'])
# df_comment.to_csv('comment.csv', index=False, encoding='utf_8_sig')


#将comment转化为embedding

# TODO: The 'openai.api_base' option isn't read in the client API. You will need to pass it when you instantiate the client, e.g. 'OpenAI(api_base="https://sailaoda.cn/v1")'
# openai.api_base = "https://sailaoda.cn/v1"

for comment in commentlist:
    response = client.embeddings.create(input = comment, model="text-embedding-ada-002")
    embedding = response['data'][0]['embedding']
    comment_embedding.append(embedding)

#保存embedding

df_embedding = pd.DataFrame({'embedding':comment_embedding})
# df_embedding.to_csv('embedding.csv', index=False, encoding='utf_8_sig')

#存储 fulldata
df= pd.concat([df_comment,df_embedding],axis=1)
df.to_csv('full_data.csv', index=False, encoding='utf_8_sig')


# 聚类，按embedding聚类，将表按聚类结果分割到不同文件中

df_embedding = pd.read_csv('full_data.csv')
features = df_embedding['embedding'].values.tolist()

for i in range(0,len(features)):
    features[i] = eval(features[i])



# #确认K值
# from sklearn.cluster import KMeans
# import matplotlib.pyplot as plt
#
#
# # 尝试不同的K值
# k_values = range(1, 30)
# sse = []  # 误差平方和
#
# for k in k_values:
#     kmeans = KMeans(n_clusters=k, n_init='auto')
#     kmeans.fit(features)
#     sse.append(kmeans.inertia_)  # 获取误差平方和
#
# # 汉字字体，优先使用楷体，找不到则使用黑体
# plt.rcParams['font.sans-serif'] = ['Kaitt', 'SimHei']
#
# # 正常显示负号
# plt.rcParams['axes.unicode_minus'] = False
#
# # 绘制肘部法则图
# plt.figure()
# plt.plot(k_values, sse, marker='o')
# plt.xlabel('K值')
# plt.ylabel('误差平方和')
# plt.title('肘部法则')
# plt.show()
#
# from sklearn.cluster import KMeans
# from sklearn.metrics import silhouette_score
#
# # 尝试不同的K值
# k_values = range(2, 30)
# silhouette_scores = []
#
# for k in k_values:
#     kmeans = KMeans(n_clusters=k, n_init='auto')
#     cluster_labels = kmeans.fit_predict(features)
#     silhouette_avg = silhouette_score(features, cluster_labels)
#     silhouette_scores.append(silhouette_avg)
#
# # 汉字字体，优先使用楷体，找不到则使用黑体
# plt.rcParams['font.sans-serif'] = ['Kaitt', 'SimHei']
#
# # 正常显示负号
# plt.rcParams['axes.unicode_minus'] = False
#
# # 绘制轮廓系数图
# plt.figure()
# plt.plot(k_values, silhouette_scores, marker='o')
# plt.xlabel('K值')
# plt.ylabel('轮廓系数')
# plt.title('轮廓系数法')
# plt.show()

df_embedding = pd.read_csv('full_data.csv')
features = df_embedding['embedding'].values.tolist()

for i in range(0,len(features)):
    features[i] = eval(features[i])

num_clusters = 3
kmeans = KMeans(n_clusters=num_clusters, n_init='auto', random_state=0)
df_embedding['cluster'] = kmeans.fit_predict(features)
for cluster_id in range(num_clusters):
    cluster_data = df_embedding[df_embedding['cluster'] == cluster_id]
    if not cluster_data.empty:
        output_file = os.path.join("resultsK3", f'cluster_{cluster_id}.csv')
        cluster_data.to_csv(output_file, index=False)
    print("output cluster {} at {}".format(cluster_id, output_file))



=======
# li jia hao
# 时间：2023/11/8 20:46
import openai
from openai import OpenAI

client = OpenAI(api_key="sk-oEVOlF1AHtU53am90a5368Ed3b8f4597B77bEcCcF49d1c40",
api_key="sk-oEVOlF1AHtU53am90a5368Ed3b8f4597B77bEcCcF49d1c40")
import pandas as pd
from sklearn.cluster import KMeans
import os
import sys
from utils import get_easyDict_from_filepath
import re

sys.path.append(os.path.join(os.getcwd(),"mmm"))
cfg = get_easyDict_from_filepath("./mmm/config.yaml")

commentlist = []
comment_embedding = []

#获得comment list



def get_commentlist(directory):
    logdir = [filename for filename in os.listdir(directory) if filename.endswith(".log")]
    if len(logdir) > 0:
        log_filename = logdir[0]
        print("log_filename:", log_filename)
    else:
        raise Exception("No log file found in {}".format(directory))

    content = open(os.path.join(directory, log_filename), "r", encoding='UTF-8').read()

    utterances = []
    regex = r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \w+)\] ([.\s\S\n\r\d\D\t]*?)(?=\n\[\d|$)"
    matches = re.finditer(regex, content, re.DOTALL)

    for match in matches:
        group1 = match.group(1)
        group2 = match.group(2)
        utterances.append("[{}] {}".format(group1, group2))

    utterances = [utterance for utterance in utterances if
                  "flask app.py" not in utterance and "OpenAI_Usage_Info" not in utterance]

    index = [i for i, utterance in enumerate(utterances) if
             "Programmer<->Chief Technology Officer on : EnvironmentDoc" in utterance]

    utterances = utterances[:index[0] - 1]

    utterances_comment = [utterance for utterance in utterances if
                          "Code Reviewer: **[Start Chat]**" in utterance and "EnvironmentDoc" not in utterance and "TestErrorSummary" not in utterance]

    for utterance in utterances_comment:
        pattern = r"Comments on Codes:(.*?)In the software, each file must strictly follow a markdown code block format"
        match = re.search(pattern, utterance, re.DOTALL)

        if match:
            extracted_text = match.group(1).strip()
            commentlist.append(extracted_text)
            print("extracted_comment")

directories = os.listdir(r'./full')
for directory in directories:
    if "_NewFeature_" not in directory:
        get_commentlist(os.path.join(r'./full', directory))


#将保存comment
df_comment = pd.DataFrame(commentlist, columns = ['comment'])
# df_comment.to_csv('comment.csv', index=False, encoding='utf_8_sig')


#将comment转化为embedding

# TODO: The 'openai.api_base' option isn't read in the client API. You will need to pass it when you instantiate the client, e.g. 'OpenAI(api_base="https://sailaoda.cn/v1")'
# openai.api_base = "https://sailaoda.cn/v1"

for comment in commentlist:
    response = client.embeddings.create(input = comment, model="text-embedding-ada-002")
    embedding = response['data'][0]['embedding']
    comment_embedding.append(embedding)

#保存embedding

df_embedding = pd.DataFrame({'embedding':comment_embedding})
# df_embedding.to_csv('embedding.csv', index=False, encoding='utf_8_sig')

#存储 fulldata
df= pd.concat([df_comment,df_embedding],axis=1)
df.to_csv('full_data.csv', index=False, encoding='utf_8_sig')


# 聚类，按embedding聚类，将表按聚类结果分割到不同文件中

df_embedding = pd.read_csv('full_data.csv')
features = df_embedding['embedding'].values.tolist()

for i in range(0,len(features)):
    features[i] = eval(features[i])



# #确认K值
# from sklearn.cluster import KMeans
# import matplotlib.pyplot as plt
#
#
# # 尝试不同的K值
# k_values = range(1, 30)
# sse = []  # 误差平方和
#
# for k in k_values:
#     kmeans = KMeans(n_clusters=k, n_init='auto')
#     kmeans.fit(features)
#     sse.append(kmeans.inertia_)  # 获取误差平方和
#
# # 汉字字体，优先使用楷体，找不到则使用黑体
# plt.rcParams['font.sans-serif'] = ['Kaitt', 'SimHei']
#
# # 正常显示负号
# plt.rcParams['axes.unicode_minus'] = False
#
# # 绘制肘部法则图
# plt.figure()
# plt.plot(k_values, sse, marker='o')
# plt.xlabel('K值')
# plt.ylabel('误差平方和')
# plt.title('肘部法则')
# plt.show()
#
# from sklearn.cluster import KMeans
# from sklearn.metrics import silhouette_score
#
# # 尝试不同的K值
# k_values = range(2, 30)
# silhouette_scores = []
#
# for k in k_values:
#     kmeans = KMeans(n_clusters=k, n_init='auto')
#     cluster_labels = kmeans.fit_predict(features)
#     silhouette_avg = silhouette_score(features, cluster_labels)
#     silhouette_scores.append(silhouette_avg)
#
# # 汉字字体，优先使用楷体，找不到则使用黑体
# plt.rcParams['font.sans-serif'] = ['Kaitt', 'SimHei']
#
# # 正常显示负号
# plt.rcParams['axes.unicode_minus'] = False
#
# # 绘制轮廓系数图
# plt.figure()
# plt.plot(k_values, silhouette_scores, marker='o')
# plt.xlabel('K值')
# plt.ylabel('轮廓系数')
# plt.title('轮廓系数法')
# plt.show()

df_embedding = pd.read_csv('full_data.csv')
features = df_embedding['embedding'].values.tolist()

for i in range(0,len(features)):
    features[i] = eval(features[i])

num_clusters = 3
kmeans = KMeans(n_clusters=num_clusters, n_init='auto', random_state=0)
df_embedding['cluster'] = kmeans.fit_predict(features)
for cluster_id in range(num_clusters):
    cluster_data = df_embedding[df_embedding['cluster'] == cluster_id]
    if not cluster_data.empty:
        output_file = os.path.join("resultsK3", f'cluster_{cluster_id}.csv')
        cluster_data.to_csv(output_file, index=False)
    print("output cluster {} at {}".format(cluster_id, output_file))



>>>>>>> 2bab9b7e5a44854fb0b7742a0bc2b17b78428139
