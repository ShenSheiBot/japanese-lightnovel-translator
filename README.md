# GPT EPUB Japanese Lightnovel Translator ｜ GPT Epub 日中轻小说翻译器


GPT EPUB Web Translator 使用API或Web Backend翻译Epub格式的日语轻小说为中文。专门对R18轻小说的结构进行适配（集成多段对话一起翻译，统一标点，针对性防止API因伦理限制翻译失败）。推荐翻译[404小说下载器](https://github.com/404-novel-project/novel-downloader)生成的Epub。

可智能跳过API因R18翻译失败的章节，完整翻译目录。已支持[SakuraLLM](https://github.com/SakuraLLM/Sakura-13B-Galgame/)。

关注知乎用户 [甚谁](https://www.zhihu.com/people/sakuraayane_justice) 支持本项目。

## 本地运行

### 前置条件
- poetry: 运行命令 `pip install poetry`以安装。
- Python 3

### 仓库克隆与依赖安装

克隆本仓库并安装必要的依赖项：

```bash
git clone https://github.com/ShenSheiBot/japanese-lightnovel-translator.git
cd japanese-lightnovel-translator
poetry env use python3.11
poetry install --no-root
```

### 日译汉设置

1. 将电子书文件放置于 `output/[Chinese Book Name]/` 目录下，并将其重命名为`input.epub`.

2. 将文件 `.env.example` 重命名为 `.env` 并更新下述配置：

```bash
CN_TITLE=[Chinese Book Name]
JP_TITLE=[Japanese Book Name]
TRANSLATION_TITLE_RETRY_COUNT=[Retry Count for Batch Translation of EPUB Titles]
```

3. 将文件 `translation.yaml.example` 重命名为 `translation.yaml` 并且填入你的 [Gemini API keys](https://aistudio.google.com/app/u/0/apikey?pli=1) 与 [Poe API keys](https://poe.com/api_key)。

```yaml
{
    "Gemini-Pro-api": {
        "name": "gemini-pro",
        "type": "api",
        "retry_count": 3,
        "key": "[Your Gemini API Key]"
    },
    "Poe-api": {
        "name": "Gemini-Pro",
        "type": "api",
        "retry_count": 1,
        "key": "[Your Poe API Key]"
    }
}
```

4. （可选）添加人名的术语表。将文件 `names.yaml` 放入`output/[Chinese Book Name]/` 目录下。示范格式如下：
```yaml
{
    "オノレ": "奥诺雷",
    "オルガ": "欧尔佳",
    "カルラ": "卡尔拉",
    "キメラ": "奇美拉",
}
```
可使用`XLM-RoBERTa.ipynb`自动生成术语表。

5. 执行以下命令以启动翻译过程：


```bash
poetry run python epubloader.py  # For EPUB files
```

翻译过程可以暂停和恢复。如果中断，只需重新运行命令即可继续。翻译完成后，译本将以中文和双语（日语+中文）两种格式出现在  `output/[Chinese Book Name]/` 目录中。

## 支持开发者

![](ad.jpg)