# Extracted from sunnweiwei/ZeroGR genir.py at 0fb7f4ebfc446e5c8a2389f3f55bbe245877408d.
# Modification: standalone extraction; original newTree class body is unchanged.
# Apache-2.0; full license and original source are retained beside this file.
import torch
from tqdm import tqdm


class newTree:
    def __init__(self, start_id, end_id, tokenizer):
        self.node_count = 1
        self.end_id = end_id
        self.start_id = start_id
        self.node_list = dict()
        self.node2doc = dict()
        self.root = self.node_count
        self.node_list[self.root] = dict()
        self.id_map = dict()
        self.tokenizer = tokenizer

    def id2node(self, id):
        return self.node_list[id]

    def add_node(self):
        self.node_count += 1
        self.node_list[self.node_count] = dict()
        return self.node_count

    def del_node(self, id):
        def dfs(id):
            pointer = self.id2node(id)
            for k, v in pointer.items():
                dfs(v)
            del self.node_list[id]
            if id in self.node2doc:
                del self.node2doc[id]

        dfs(id)

    def show(self):
        results = []

        def dfs(id, path):
            pointer = self.id2node(id)
            if len(pointer) == 0:
                results.append(path)
                return
            for k, v in pointer.items():
                dfs(v, path + [k])

        dfs(self.root, [])
        return results

    def set(self, path, id):
        now_id = self.root
        for i in path:
            pointer = self.id2node(now_id)
            if i not in pointer:
                pointer[i] = self.add_node()
            now_id = pointer[i]
        if now_id not in self.node2doc:
            self.node2doc[now_id] = []
        self.node2doc[now_id].append(id)

    def set_short(self, path, ids):
        now_id = self.root
        for i in path:
            pointer = self.id2node(now_id)
            if i not in pointer:
                pointer[i] = self.add_node()
                now_id = pointer[i]
                if i == self.end_id:
                    break
                pointer = self.id2node(now_id)
                pointer[self.end_id] = self.add_node()
                now_id = pointer[self.end_id]
                break
            now_id = pointer[i]
        if now_id not in self.node2doc:
            self.node2doc[now_id] = []
        self.node2doc[now_id].extend(ids)

    def remove(self, path):
        def dfs(id, path):
            # print(path)
            if len(path) == 0:
                return True
            pointer = self.id2node(id)
            if path[0] not in pointer:
                return True  # bug?
                # raise ValueError("Path not found")
            temp = dfs(pointer[path[0]], path[1:])
            if (id == self.root or len(pointer) > 1) and temp:
                self.del_node(pointer[path[0]])
                del pointer[path[0]]
                temp = False
            return temp

        dfs(self.root, path)

    def get(self, path):
        now_id = self.root
        for i in path:
            pointer = self.id2node(now_id)
            if i not in pointer:
                return None
            now_id = pointer[i]
            if i == self.end_id:
                break
        try:
            return self.node2doc[now_id]
        except:
            return None

    def build(self, docs):
        error_cnt = 0
        encodes = []
        for doc in docs:
            encode = self.tokenizer.encode(doc["gist"], add_special_tokens=False)
            encode = encode[:1000] + [self.end_id]
            self.set(encode, doc["id"])
            encodes.append(encode)
        for encode in tqdm(encodes):
            try:
                ids = self.get(encode)
                self.remove(encode)
                self.set_short(encode, ids)
            except:
                error_cnt += 1
        temp = self.show()
        cnt = sum([len(self.get(i)) for i in temp])
        return {
            "docs": len(docs),
            "save_docs": cnt,
            "nodes": len(temp),
            "avg_token": sum([len(i) for i in temp]) / len(temp),
        }

    def last_id(self, lst, target):
        if target is None:
            return 0
        if isinstance(target, int):
            target = [target]
        target_len = len(target)
        for i in range(len(lst) - target_len, -1, -1):
            if lst[i : i + target_len] == target:
                return i + target_len
        return -1

    def __call__(self, batch_id, path):
        if isinstance(path, torch.Tensor):
            path = path.cpu().tolist()
        start_pos = self.last_id(path, self.start_id)
        path = [] if start_pos < 0 else path[start_pos:]
        now_id = self.root
        for i in path:
            pointer = self.id2node(now_id)
            if i not in pointer:
                return [self.end_id]
            now_id = pointer[i]
        results = list(self.id2node(now_id).keys())
        if len(results) == 0:
            results = [self.end_id]
        return results
