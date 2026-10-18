import Foundation

/// Built-in sample library so the full playback/download experience can be
/// tried (and App Review can verify it) without a Notion account.
/// Media files ship inside the app bundle under Resources/Demo.
enum DemoData {
    static let databaseID = "demo-database"
    static let databaseTitle = "サンプル: ラジオ録音"

    static let schema: [PropertySchema] = [
        PropertySchema(name: "番組名", type: "title"),
        PropertySchema(name: "音声ファイル", type: "files"),
        PropertySchema(name: "チャンネル", type: "select"),
        PropertySchema(name: "放送日", type: "date"),
        PropertySchema(name: "時間帯", type: "rich_text"),
        PropertySchema(name: "録音時間(分)", type: "number"),
        PropertySchema(name: "キーワード", type: "multi_select"),
    ]

    static let mapping = DatabaseMapping(
        mediaProperty: "音声ファイル",
        titleProperty: "番組名",
        displayProperties: ["チャンネル", "放送日", "時間帯"],
        sortProperty: "放送日",
        sortDescending: true
    )

    static var items: [LibraryItem] {
        [
            item(
                pageID: "demo-page-1", title: "朝の朗読: 宮沢賢治セレクション",
                channel: "R1", date: "2026年10月17日", slot: "05:10-05:40", minutes: "30",
                keywords: "朗読, 文学", file: "demo-speech-1.m4a"
            ),
            item(
                pageID: "demo-page-2", title: "落語特選: 古典の味わい",
                channel: "R1", date: "2026年10月16日", slot: "21:05-21:55", minutes: "50",
                keywords: "落語", file: "demo-speech-2.m4a"
            ),
            item(
                pageID: "demo-page-3", title: "英語ニュース シャドーイング練習",
                channel: "R3", date: "2026年10月15日", slot: "07:15-07:30", minutes: "15",
                keywords: "英語", file: "demo-speech-1.m4a"
            ),
            item(
                pageID: "demo-page-4", title: "クラシック名曲アーカイブ（映像つき）",
                channel: "FM", date: "2026年10月14日", slot: "19:30-20:00", minutes: "30",
                keywords: "音楽, 映像", file: "demo-video-1.mp4"
            ),
            item(
                pageID: "demo-page-5", title: "深夜のジャズ便り",
                channel: "FM", date: "2026年10月13日", slot: "23:00-23:50", minutes: "50",
                keywords: "音楽", file: "demo-speech-2.m4a"
            ),
        ]
    }

    private static func item(pageID: String, title: String, channel: String, date: String,
                             slot: String, minutes: String, keywords: String, file: String) -> LibraryItem {
        LibraryItem(
            pageID: pageID,
            databaseID: databaseID,
            title: title,
            propertyTexts: [
                "番組名": title,
                "音声ファイル": file,
                "チャンネル": channel,
                "放送日": date,
                "時間帯": slot,
                "録音時間(分)": minutes,
                "キーワード": keywords,
            ],
            propertyOrder: schema.map(\.name),
            mediaFiles: [MediaFileRef(name: file, urlString: file, isExternal: true)],
            pageURLString: nil,
            createdAt: nil,
            lastEditedAt: nil
        )
    }

    /// Bundle URL for a demo media file name.
    static func bundleURL(forFileName name: String) -> URL? {
        let base = (name as NSString).deletingPathExtension
        let ext = (name as NSString).pathExtension
        return Bundle.main.url(forResource: base, withExtension: ext, subdirectory: "Demo")
            ?? Bundle.main.url(forResource: base, withExtension: ext)
    }
}
