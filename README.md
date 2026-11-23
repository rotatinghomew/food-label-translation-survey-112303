# 糖标注理解调查的译文等值与补访

当前资料覆盖多语问卷邀请、题序、桥接与预约资料。记录均为合成数据，使用 UTF-8 编码及带列名的 CSV。

## 运行

使用 Python 3.11。分析依赖在 `requirements.txt` 中锁定，本地环境可运行 `python3 -m pip install -r requirements.txt` 安装。在项目根目录查看文件列和记录数，并核对交接格式。

```sh
python3 inspect_inputs.py data
python3 -m unittest discover -s tests -v
```

## 记录约定

答项数值 0 表示误解，1 表示正确，空白表示未观察。桥接层是预先声明适用的熟练读者或全体读者，selection_p 是分层抽取概率。题项所测概念见 items，桥接使用同一参与者标识。电话和现场是不同邀请框，邀请标识为轮次内唯一。

- `items.csv` 不同版次的题项和题序，anchor 标出拟用于桥接的共同题。
- `invitations.csv` 邀请总框，invited_at 为空表示未实际邀请。
- `responses.csv` 逐项编码，bridge 区分原版、盲复测和先看答案后访谈。
- `corrections.csv` 回答撤回及问卷停用，target 以 kind 决定含义。
- `appointments.csv` 正在使用和未来可用的复测资源，空 person 表示开放席位。
- `rounds.csv` 问卷复测设计中各偏好语言主版、桥接资格及计划公布时点。
