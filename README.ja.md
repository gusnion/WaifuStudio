# WaifuStudio v2.0 — ローカルアニメ制作スタジオ

<p align="center">
  <img src="static/waifustudio-icon.png" width="112" alt="WaifuStudio のアイコン">
</p>

[![バージョン](https://img.shields.io/badge/version-2.0.0-ff4081.svg)](https://github.com/gusnion/WaifuStudio)
[![ライセンス: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![リファレンス GPU](https://img.shields.io/badge/Reference%20GPU-RTX%203060%2012GB-76b900.svg)](https://www.nvidia.com)
[![エンジン](https://img.shields.io/badge/Engine-ComfyUI%20Backend-orange.svg)](https://github.com/comfyanonymous/ComfyUI)
[![デフォルトでローカル](https://img.shields.io/badge/Local-by%20default-success.svg)]()
[![Patreon](https://img.shields.io/badge/Patreon-gusnion-ff424d.svg)](https://www.patreon.com/gusnion)

> [English](README.md) | [Español](README.es.md) | 日本語 | [中文](README.zh.md) | [Русский](README.ru.md)

WaifuStudio は、アニメ画像とショート動画のためのローカルファーストの制作ワークスペースです。画像生成、キャラクター参照、動画生成、編集、アップスケール、Timeline での組み立て、ギャラリー管理を 1 つの Web インターフェースに統合し、推論エンジンとして ComfyUI を使用します。

## 言語

インターフェースは **英語（デフォルト）**、**スペイン語**、**日本語**、**簡体字中国語**、**ロシア語** で利用できます。切り替えには上部バーの地球儀ボタンを使用します。技術的なモデル名、prompt の例、ユーザーコンテンツ、および一部のバックエンドのエラーメッセージは元の言語のままです。

本アプリケーションは、単一の NVIDIA GPU と Windows デスクトップを中心に設計されています。アカウント、クラウドサービス、テレメトリは必要ありません。インストーラーは Python、ComfyUI、FFmpeg をポータブルディレクトリに保持します。

> [!WARNING]
> **状態と範囲**: 本プロジェクトは独立したもので、現状のまま（"as is"）提供され、いかなる保証も行いません。以下のリファレンス構成を中心に開発・検証されています。他の GPU、OS、ワークフローでも動作する可能性はありますが、公式な検証は行っていません。未完成な部分があるものとして扱い、プロジェクトと生成したメディアのバックアップを保管してください。

## 含まれる機能

| モジュール | 状態 | 内容 |
|---|---|---|
| **Windows インストーラー** | 利用可能 | ポータブルな Python 環境、ComfyUI、カスタムノード、モデル、FFmpeg/FFprobe、アプリのショートカットをセットアップする。 |
| **画像と OC Maker** | 利用可能 | Anima 2.9B と SDXL/Illustrious に対応。prompt ゾーン、LoRA の選択、キャラクタープロフィール、参照画像、任意の LoRA トレーニングを提供する。 |
| **prompt アシスタント** | 利用可能 | ローカルの Danbooru タグインデックスに加え、prompt の拡張と画像キャプション生成用の任意の CPU LLM を提供する。 |
| **H3 動画** | 利用可能 | I2V、FLF2V、Ref2VA、V2V モードでの 8 ステップ VideoDeltaNet 生成。ネイティブ音声と短い prompt テンプレートを備える。 |
| **エディター** | 利用可能 | Qwen-Image 2.1 による指示ベースの編集。最大 10 枚の参照画像と L0–L3 のポーズプリセットに対応。マスクベースのインペイントはこのバージョンには含まれない。 |
| **Timeline** | 利用可能 | クリップと静止画を並べ、長さを設定し、フェード/ズームを適用し、クリップをミュートし、外部音声を追加し、I2V/FLF2V でクリップを継続し、MP4 を書き出す。特化型のシーケンサーであり、フル NLE ではない。 |
| **Upscaler** | 利用可能 | GAN、Hires Fix、Qwen Remaster モードによる画像アップスケールに加え、RCAS/Adaptive USM のシャープ化と RIFE 補間を提供する。動画のアップスケールは 1 ジョブあたり 300 フレームまで。 |
| **ギャラリーとキュー** | 利用可能 | SQLite ベースのギャラリー、ジョブ履歴、すべてのタブで共有される単一 GPU の FIFO キュー。 |

## インストール（Windows）

### 開始前の確認

- Windows 10/11 64 ビット。
- NVIDIA GPU。リファレンス環境では RTX 3060（12 GB）を使用。
- NVIDIA ドライバー 570 以降（スタックは CUDA 13 を使用）。
- 自動アップデートを使用する場合は Git for Windows。ZIP インストールは Git なしで動作します。
- モデル一式に十分な空きディスク容量。インストーラーはサイズを表示し、ダウンロード前に確認を求めます。
- 短いローカルパスのほうが同期フォルダーより安全です。例: `C:\AI\WaifuStudio`。
- 古いコピーが実行中の場合は、先に `stop.bat` で停止してください。

### 方法 A: Git clone（推奨）

1. リポジトリを clone します:

```powershell
git clone https://github.com/gusnion/WaifuStudio.git
cd WaifuStudio
```

2. インストールします:

```powershell
install.bat
```

インストーラーは、分離された Python 環境、ComfyUI、カスタムノード、FFmpeg、ショートカットを作成します。ダウンロードするモデルも確認します。再実行しても安全で、既存の内容を検証し、不足しているものだけをインストールします。

3. アプリを起動します:

```powershell
start.bat
```

専用ウィンドウで `http://127.0.0.1:8765` を開きます。

4. 停止または診断します:

```powershell
stop.bat
healthcheck.bat
```

モデルが既にディスク上にあり、エンジンとアプリだけが必要な場合:

```powershell
install.bat -SkipModels
```

推奨モデルがまだ必要な場合は、初回インストールで `-SkipModels` を使用しないでください。

### 方法 B: ZIP

1. ZIP をダウンロードし、新しいフォルダーに展開します。古いインストールの上に展開しないでください。
2. 新しいフォルダー内で `install.bat` を実行します。
3. `start.bat` を実行します。
4. そのフォルダーを使い続けてください。ZIP インストールには Git のメタデータがないため、`update.bat` では更新できません。

### コマンド

```text
start.bat        アプリとエンジンを起動
stop.bat         アプリとエンジンを停止
update.bat       Git インストールを更新
healthcheck.bat  パスとサービスを確認
start_engine.bat ComfyUI のみを起動
stop_engine.bat  ComfyUI のみを停止
```

FFmpeg はデフォルトでインストールされます。最小構成向けに `-SkipFfmpeg` も用意されていますが、その場合 Timeline の書き出しと連結は動作しません。`install.bat` はアプリのアイコン付きで `WAIFUSTUDIO.lnk` も作成します。フォルダーを移動した場合は、`scripts\create_shortcut.ps1` を実行するか、インストーラーを再実行してください。

## アップデート

### Git インストール

`update.bat` はアプリを停止し、`data/` と `ComfyUI/user/` を `%LOCALAPPDATA%\WaifuStudio\backups\update-<date>` に保存し、`git pull --ff-only` を実行して、インストーラーを再実行したうえでアプリを起動します。

アップデートの前に:

- 実行中の ComfyUI ジョブを完了またはキャンセルします。
- `git status --short` に追跡対象の変更が表示される場合は、コミットするか保存します。アップデーターはそれらの上書きを拒否します。

通常のアップデート:

```powershell
update.bat
```

何も変更せずに事前確認する場合:

```powershell
update.bat -DryRun
```

便利なバリエーション:

```powershell
update.bat -NoStart        # アプリを開かずに更新
update.bat -InstallModels  # 不足しているモデルもダウンロード
```

デフォルトでは新しいモデルをダウンロードしません。リポジトリに追跡対象のローカル変更がある場合、現在のブランチが `main` でない場合、または ComfyUI にまだアクティブなジョブがある場合は実行を拒否します。`install.bat -Update` は `update.bat` のエイリアスです。

### ZIP インストール

ZIP インストールにはインプレースのアップデーターがありません。手動で更新します:

1. `stop.bat` でアプリを停止します。
2. `data/`、`ComfyUI/user/`、`.env`、`config.local.json` が存在する場合はバックアップします。モデルを再ダウンロードする予定がない場合は `ComfyUI/models/` もバックアップします。
3. 新しい ZIP を新しいフォルダーに展開します。
4. 古いフォルダーから新しいフォルダーへ、`data/`、`ComfyUI/user/`、および保持した場合は `ComfyUI/models/` をコピーします。
5. 新しいフォルダーで `install.bat` を実行します。
6. 起動し、古いフォルダーを削除する前にギャラリーとプロジェクトを確認します。

Git アップデーターはタイムスタンプ付きのバックアップを残します。新しいバージョンをテストするまで保持してください。

現在のアイコンは暫定です。ソースは `waifystudioicon.ico` で、アプリは `static/favicon.ico` を配信し、README は `static/waifustudio-icon.png` を使用しています。

## 画像モデルと LoRA の追加

リポジトリにはサードパーティのチェックポイントや LoRA は含まれていません。インストーラーがスターターセットをダウンロードし、追加のファイルは手動でコピーします。アプリ内のモデルブラウザーはまだありません。

### ファイルの配置場所

| アセット | フォルダー | 形式 | 備考 |
|---|---|---|---|
| SDXL チェックポイント | `ComfyUI/models/checkpoints/` | `.safetensors` | CLIP と VAE を含む。Illustrious、Pony、NoobAI 系の SDXL チェックポイントもこのパスを使用する。 |
| Anima 2.9B UNET | `ComfyUI/models/diffusion_models/` | `.safetensors` | 以下に示す Anima のテキストエンコーダーと VAE が必要。 |
| Anima LoRA | `ComfyUI/models/loras/anima/` | `.safetensors` | サブフォルダーは任意だが、ファミリーの自動判定に役立つ。 |
| SDXL 系 LoRA | `ComfyUI/models/loras/sdxl/` | `.safetensors` | SDXL/Illustrious のチェックポイントと組み合わせてのみ使用する。 |
| Anima テキストエンコーダー | `ComfyUI/models/text_encoders/` | `.safetensors` | 想定されるファイル名: `qwen_3_06b_base.safetensors`。 |
| Anima VAE | `ComfyUI/models/vae/` | `.safetensors` | 想定されるファイル名: `qwen_image_vae.safetensors`。 |

`.safetensors` を使用してください。自動スキャナーは `.safetensors` ファイルのみを登録し、`.ckpt` や `.pt` ファイルは検出されません。

### ダウンロードとインストール

1. モデルを公式ページからダウンロードします。通常は Civitai または Hugging Face です。
   - Civitai では、ワークフロー、プレビュー、トレーニングデータではなく、**Model** または **LoRA** のダウンロードを使用します。
   - Hugging Face では、**Files and versions** から `.safetensors` ファイルをダウンロードします。
   - 年齢制限のあるモデルは、アカウントと利用規約への同意が必要です。
2. ファイルを表の該当フォルダーにコピーします。
3. Anima を使用する場合は、必須の Anima エンコーダー/VAE の名前を変更しないでください。
4. アプリを開き、画像タブの **再読み込み**ボタンを押すか、`GET /api/models?scan=1` を呼び出します。
5. **LoRA を選択 → ライブラリを管理**を開いて LoRA を登録するか、`POST /api/loras/scan` でスキャナーに検出させます。
6. モデルを選択し、プロジェクトで使用する前に小さなテスト画像を 1 枚生成してください。

サブフォルダーは再帰的にスキャンされます。LoRA を `loras/anima/...` や `loras/sdxl/...` のように整理することは任意ですが、ファイルのメタデータがベースモデルを特定できない場合に役立ちます。

### 対応する画像ファミリー

| ファミリー | 対応 | 備考 |
|---|---|---|
| **Anima 2.9B** | はい | 主要なネイティブファミリー。28 ブロックのモデルが安全な選択肢。40 ブロックの派生も存在するが、すべての 28 ブロック LoRA が問題なく転用できるわけではない。 |
| **SDXL** | はい | 独自の CLIP と VAE を持つチェックポイント。 |
| **Illustrious** | はい | SDXL アーキテクチャ。SDXL チェックポイントとして扱う。 |
| **Pony** | はい | SDXL アーキテクチャ。prompt の慣習が異なる。 |
| **NoobAI 系 SDXL** | はい | SDXL アーキテクチャ。prompt の慣習が異なる。 |
| **SD 1.5 / SD 2.1** | いいえ | 検証対象外。アプリは SDXL のデフォルトとローダーを前提とする。 |
| **Flux、Qwen-Image などのアーキテクチャ** | いいえ | 画像タブは Anima と SDXL 向けに構築されている。Qwen-Image はこのタブではなくエディターに属する。 |

### 対応する LoRA

- **Anima LoRA** は Anima UNET と組み合わせます。
- **SDXL/Illustrious/Pony LoRA** は SDXL チェックポイントと組み合わせます。
- ファミリーを混在させないでください。Anima 向けにトレーニングされた LoRA は SDXL では正しく動作せず、その逆も同様です。
- H3 と Wan の LoRA は動画ワークフローに属し、画像タブのものではありません。
- アプリは LoRA のメタデータから trigger を読み取ろうとします。見つからない場合は、ライブラリで trigger を手動入力してください。
- スタイル LoRA では `0.6–0.8`、キャラクター LoRA では `0.8–1.0` 程度の重みから始め、そこから調整してください。

### この画面から追加できないもの

- ControlNet、IP-Adapter、textual inversion、embeddings は画像タブでは公開されていません。
- 個別の VAE セレクターはありません。Anima は固定のエンコーダー/VAE のペアを使用し、SDXL チェックポイントは独自のものを同梱しています。
- Upscaler のファイルは独立した固定カタログです。新しい `.pth` を `upscale_models` にコピーしても、Upscaler のドロップダウンには追加されません。
- H3 の動画モデルとプリセットは、ファイルを `checkpoints` に置くだけではインストールされません。

生成物を公開する前にモデルのライセンスを確認してください。Anima のモデルは非商用です。SDXL と Civitai のモデルにはそれぞれの利用規約があります。

## リファレンス構成

以下は開発と検証に使用したハードウェアとソフトウェアです。最低要件ではありません。

| コンポーネント | リファレンス |
|---|---|
| GPU | NVIDIA GeForce RTX 3060、12 GB |
| CPU | AMD Ryzen 7 5700X、8 コア |
| RAM | 32 GB DDR4 |
| OS | Windows 10 64 ビット |
| エンジン | ComfyUI v0.37.4 |
| Python | CPython 3.12.12、分離環境 |
| 推論 | PyTorch 2.11.0 + CUDA 13.0 |

ワークフローは 12 GB の予算と 1 度に 1 ジョブという条件に合わせて調整されています。任意の Qwen3.5-9B アシスタントは CPU 上で動作するため、ComfyUI の VRAM を消費しません。

サポート対象のインストール方法は Windows です。コアは標準的な FastAPI、ComfyUI、バニラ JavaScript で構成されています。Linux サーバー/LAN モードは計画中ですが、まだ利用できません。

## 現在の制限

- 単一 GPU、FIFO キュー。長時間のジョブは完了するまで他のタブをブロックします。
- H3 が生成するのは短いセグメントです。1 回の生成あたり 15 秒で、対応している場合は連結出力を行います。
- ネイティブの動画アップスケーラーは 1 バッチを処理し、300 フレームを超える動画は拒否します。長い動画には外部ツールが必要です。
- Timeline は意図的に小規模です。プレイヘッド、トリムハンドル、ドラッグ&ドロップ、波形編集はまだありません。
- このバージョンにはリップシンクも自動音声ナレーションもありません。
- クラウド推論、リモート GPU レンタル、モデルマーケットプレイスはまだ統合されていません。
- アプリ内ガイドは改訂中です。利用可能な機能については、README と実際の UI を正とみなしてください。

## ロードマップ

以下は計画中または検討中の項目です。約束でも日程でもなく、明示されていない限り利用できません。

### 近い将来

- **VRAM 別のモデルプリセット**と検証済みのモデルマネージャー。インストール時に 12 GB のカードを前提としないようにする。
- **Linux Studio モード**: ローカルネットワーク向けのヘッドレスサーバーで、シングルユーザー向けの Windows アプリとは別に提供する。
- **リモート ComfyUI/GPU 対応**（永続的なモデルボリューム付き）。長時間のジョブがローカル GPU に依存しないようにする。
- **ローカルエージェントツール**: CLI、スキル、DSH モード。API 経由でアプリを操作できるようにする。
- **Timeline のシーンキュー**と、ジョブを再開できるスクリプトベースのシーンディレクター。

### 検討中

- **Chatterbox ナレーション**（スペイン語のボイスオーバー）。任意のリップシンクは別ステップとして提供する。
- **Video2X 統合**（長い動画のアップスケール）。ComfyUI に取り込むのではなく、外部ツールとして維持する。
- **Wan 2.2 ワークフロープロファイル**。Artelive にクレジットされるコミュニティのワークフロー集を含む。
- **Civitai のモデルブラウザー/ダウンローダー**。API の制限、ライセンス、年齢制限コンテンツのルールに従う。
- **LTX 2.5**: 検討したが、現状の形では 12 GB の GPU では実用的でない。
- **Timeline の NLE 強化**: プレイヘッド、トリミング、ドラッグ&ドロップ、波形。

## 開発

バージョン 2.0 は、元のアプリケーションに対して安定化とドキュメント整備を行うパスです。修正作業、テスト作業、エージェント向けの基盤整備は、**DSH** を使用して **DeepSeek V4.1 Flash 1017** とともに継続されました。

オフラインスイートは現在 1,614 件のテストを実行します。README は現状のアプリを記述しており、計画のみの機能はロードマップに記載しています。

## サポート

開発は独立して行われており、アプリケーションは MIT ライセンスのままです。テスト、ドキュメント、メンテナンスに費やされる時間を支援したい場合は、Patreon ページがあります:

https://www.patreon.com/gusnion

支援は任意であり、アプリケーションのいかなる部分も解放したり制限したりするものではありません。

## ライセンスとクレジット

- **MIT License** の下で公開されています。いかなる保証も提供されません。
- ComfyUI、MiniMax H3 VDN、Anima、Qwen、FFmpeg の上に構築されています。
- **Wan 2.2 のワークフロー研究と 8 GB ワークフロー集**: Artelive（コミュニティによる貢献。統合は保留中）。
