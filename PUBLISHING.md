# GitHub 公開準備

## 範圍

依專案所有者確認，程式碼、ROS 2 package、資料集、兩個 TFLite 模型與示範影片均可公開，這次整理沒有刪除或排除這些資產。

.gitignore 排除環境密鑰、私鑰、虛擬環境、ROS 建置產物、runtime 資料、資料庫、logs、訓練 runs 與備份。這些排除規則是針對未來產物，不會刪除本機檔案。

## 修改

- 新增根目錄 README、Python 依賴清單、忽略規則與本文件。
- 將獨立程式與 ROS legacy 的模型設定改為 best_float16.tflite，相對於啟動工作目錄。
- 將 launch 預設模型路徑改為相同檔名；README 使用明確 model_path argument。
- 更新兩份既有 ROS 文件中的模型路徑範例。
- 不更動辨識、追蹤、馬達、夾具或刺破控制流程。

## 待確認

- 正式 LICENSE：ROS metadata 目前宣告 MIT，但缺少正式條款；請確認授權方式與著作權人。允許公開不等於已選定第三方可使用的授權。
- 模型 provenance、訓練方式、實測精度與兩個模型差異尚無完整紀錄。
- 資料集與影片的公開權由所有者確認，本次未逐張檢視影像或讀取二進位 metadata。
- 影像資料約 561 MiB、影片約 35 MiB；一般 clone 會較大。若日後資產增長，可另外評估大檔儲存。
- Python 依賴未鎖版；Python、ROS 發行版、Arduino 板型及 TFLite backend 的相容組合尚待實機確認。
- 啟動會操作硬體；ROS 軟體停止可能延遲，Arduino 沒有通訊 watchdog。須備妥實體斷電措施。

## 本次驗證

- 五個既有檔案已與預期文字比對，確認只有指定模型路徑替換。
- 獨立版與 ROS legacy 控制程式的檔案雜湊一致。
- ROS package.xml 可解析；必要忽略規則存在，資料集、模型與既有影片未被排除。
- 對程式及文件進行啟發式敏感值與本機路徑掃描，未發現符合本次規則的項目；不等同完整安全稽核。
- 目前環境找不到可用的 Python、colcon 或 Arduino CLI，未執行 Python 語法編譯、ROS 建置、模型推論或硬體測試。

## 提交

整理前此目錄尚未有 Git metadata，因此沒有既有提交歷史可稽核。初次文件整理時未建立 commit 或 push；後續發布另依專案所有者指示執行。

建立 repository 後先檢查忽略規則、候選檔案清單及大小。公開資產包含大量檔案，確認暫存區只包含預期內容後再提交。

.gitignore 不會移除已追蹤檔案或既有歷史中的資料。未來若加入其他 repository 的歷史，也須重新檢查。

建議 commit message：

```text
Prepare BalloonPopBot for public GitHub release
```
