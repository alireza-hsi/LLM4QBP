import argparse
import os

import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer

parser = argparse.ArgumentParser(description='argparse')
parser.add_argument('--n', type=int, default=2,
                    help="N in Ngram")
args = parser.parse_args()

n = args.n #关键词的词数

all_ngrams = []
cluster_documents = []

for cluster_file in os.listdir("resultsK3/"):
    df = pd.read_csv(os.path.join("resultsK3", cluster_file))
    comments = df['comment'].tolist()
    cluster_documents.append(" ".join(comments))

tfidf_vectorizer = TfidfVectorizer(ngram_range=(n, n))
tfidf_matrix = tfidf_vectorizer.fit_transform(cluster_documents)

feature_utterances = tfidf_vectorizer.get_feature_names_out()

for i, cluster_doc in enumerate(cluster_documents):
    doc_tfidf = tfidf_matrix[i].toarray().flatten()
    ngram_indices = doc_tfidf.argsort()[-10:][::-1]  # 选择前10个高权重N-grams
    ngram_weights = [doc_tfidf[idx] for idx in ngram_indices]
    ngram_words = [feature_utterances[idx] for idx in ngram_indices]

    # 打印每个聚类的高权重N-grams
    print(f"Top {n}-grams in Cluster {i}:")
    for word, weight in zip(ngram_words, ngram_weights):
        print(f"{word}: {weight}")
    print("\n\n")
