"""pptx/docx共通: MS-OFFCRYPTO暗号化の判定ヘルパー。

Office文書の保護には性質の異なる2種類がある。

- **開くパスワード保護**（ECMA-376 standard/agile暗号化）: パスワードさえあれば
  ローカルで復号できる。msoffcrypto-tool が対応。
- **IRM/Azure RMS保護**（Microsoft情報保護ラベルによる「暗号化」ラベル、
  ECMA-376 extensible暗号化）: コンテンツキーがAzure ADの利用者IDに紐づく
  ライセンスサーバ（RMSサーバ）からのみ取得できる。パスワードという概念が
  存在せず、msoffcrypto-tool（オフラインのパスワード復号ツール）はこの方式を
  そもそもサポートしない。EncryptionInfoストリームのバージョン
  （versionMajor 3/4, versionMinor 3 = Extensible Encryption）で判定できる。
"""
from __future__ import annotations

from pathlib import Path


class PasswordRequiredError(RuntimeError):
    """開くパスワードで暗号化されているが、パスワードが未指定の場合。"""


class IRMProtectedError(RuntimeError):
    """Microsoft情報保護ラベル(IRM/Azure RMS)で保護されており、パスワードでは復号できない場合。"""


IRM_GUIDANCE = (
    "このファイルはMicrosoft情報保護ラベル（IRM/Azure RMS）で保護されています。"
    "開くパスワードとは異なりAzure ADの利用者IDに紐づくライセンスサーバとの通信が必要なため、"
    "msoffcrypto-tool（本スクリプトが使う復号ライブラリ）では復号できません"
    "（--password 等を指定しても解決しません）。"
    "ラベル/保護を解除する権限を持つ人がOffice上でファイルを開き、"
    "情報保護ラベルの解除または「アクセス制限」の解除を行った上で、"
    "保護なしの複製をraw/に配置し直してから再実行してください。"
)


def is_encrypted(path: Path) -> bool:
    """暗号化の有無を判定する。

    IRM(Extensible Encryption)で保護されている場合は判定できないため、
    IRMProtectedError を送出する（呼び出し側でパスワード入力を促さないため）。
    """
    import msoffcrypto  # type: ignore
    from msoffcrypto.exceptions import DecryptionError  # type: ignore

    with open(path, "rb") as f:
        try:
            office_file = msoffcrypto.OfficeFile(f)
        except DecryptionError as e:
            if "Extensible Encryption" in str(e):
                raise IRMProtectedError(IRM_GUIDANCE) from e
            raise
        return office_file.is_encrypted()
