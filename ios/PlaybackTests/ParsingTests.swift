import XCTest
@testable import Playback

final class NotionIDTests: XCTestCase {
    func testExtractFromNotionURL() {
        let url = "https://app.notion.com/p/kabu-labo2/6dc536e3d4404708a92ef5554353fa0d?v=0620491a6d394af38dcd60a3be23904e"
        XCTAssertEqual(NotionID.extract(from: url), "6dc536e3-d440-4708-a92e-f5554353fa0d")
    }

    func testExtractDashedUUID() {
        XCTAssertEqual(
            NotionID.extract(from: "  6DC536E3-D440-4708-A92E-F5554353FA0D  "),
            "6dc536e3-d440-4708-a92e-f5554353fa0d")
    }

    func testExtractRaw32Hex() {
        XCTAssertEqual(
            NotionID.extract(from: "6dc536e3d4404708a92ef5554353fa0d"),
            "6dc536e3-d440-4708-a92e-f5554353fa0d")
    }

    func testExtractRejectsNoID() {
        XCTAssertNil(NotionID.extract(from: "https://example.com/no-id-here"))
        XCTAssertNil(NotionID.extract(from: ""))
    }
}

final class MappingSuggestionTests: XCTestCase {
    func testSuggestedMappingForRadioSchema() {
        let schema = [
            PropertySchema(name: "番組名", type: "title"),
            PropertySchema(name: "チャンネル", type: "select"),
            PropertySchema(name: "放送日", type: "date"),
            PropertySchema(name: "時間帯", type: "rich_text"),
            PropertySchema(name: "録音時間(分)", type: "number"),
            PropertySchema(name: "キーワード", type: "multi_select"),
            PropertySchema(name: "音声ファイル", type: "files"),
        ]
        let mapping = DatabaseMapping.suggested(from: schema)
        XCTAssertEqual(mapping.mediaProperty, "音声ファイル")
        XCTAssertEqual(mapping.titleProperty, "番組名")
        XCTAssertEqual(mapping.sortProperty, "放送日")
        XCTAssertTrue(mapping.sortDescending)
        XCTAssertFalse(mapping.displayProperties.contains("音声ファイル"))
        XCTAssertFalse(mapping.displayProperties.contains("番組名"))
        XCTAssertLessThanOrEqual(mapping.displayProperties.count, 3)
    }

    func testSuggestedMappingWithoutFiles() {
        let schema = [PropertySchema(name: "名前", type: "title")]
        let mapping = DatabaseMapping.suggested(from: schema)
        XCTAssertEqual(mapping.mediaProperty, "")
    }
}

final class PropertyFormattingTests: XCTestCase {
    func testSelectAndMultiSelect() {
        let select: NotionParsing.JSONObject = ["type": "select", "select": ["name": "R1"] as [String: Any]]
        XCTAssertEqual(NotionParsing.displayString(forPropertyValue: select), "R1")

        let multi: NotionParsing.JSONObject = [
            "type": "multi_select",
            "multi_select": [["name": "落語"], ["name": "英語"]],
        ]
        XCTAssertEqual(NotionParsing.displayString(forPropertyValue: multi), "落語, 英語")
    }

    func testNumberAndDate() {
        let number: NotionParsing.JSONObject = ["type": "number", "number": NSNumber(value: 50)]
        XCTAssertEqual(NotionParsing.displayString(forPropertyValue: number), "50")

        let date: NotionParsing.JSONObject = ["type": "date", "date": ["start": "2026-10-18"]]
        XCTAssertFalse(NotionParsing.displayString(forPropertyValue: date).isEmpty)
    }

    func testTitleRichText() {
        let title: NotionParsing.JSONObject = [
            "type": "title",
            "title": [["plain_text": "朝の"], ["plain_text": "番組"]],
        ]
        XCTAssertEqual(NotionParsing.displayString(forPropertyValue: title), "朝の番組")
    }

    func testMediaFilesExtraction() {
        let files: NotionParsing.JSONObject = [
            "type": "files",
            "files": [
                ["name": "a.m4a", "type": "file",
                 "file": ["url": "https://example.com/a.m4a", "expiry_time": "2026-10-18T00:00:00.000Z"]],
                ["name": "b.mp4", "type": "external",
                 "external": ["url": "https://example.com/b.mp4"]],
            ] as [[String: Any]],
        ]
        let refs = NotionParsing.mediaFiles(forPropertyValue: files)
        XCTAssertEqual(refs.count, 2)
        XCTAssertEqual(refs[0].name, "a.m4a")
        XCTAssertFalse(refs[0].isExternal)
        XCTAssertEqual(refs[0].kind, .audio)
        XCTAssertTrue(refs[1].isExternal)
        XCTAssertEqual(refs[1].kind, .video)
    }
}

final class LibraryItemParsingTests: XCTestCase {
    func testLibraryItemFromPageJSON() {
        let schema = DemoData.schema
        let page: NotionParsing.JSONObject = [
            "id": "page-1",
            "url": "https://www.notion.so/page-1",
            "created_time": "2026-10-01T00:00:00.000Z",
            "last_edited_time": "2026-10-02T00:00:00.000Z",
            "properties": [
                "番組名": ["type": "title", "title": [["plain_text": "テスト番組"]]],
                "音声ファイル": [
                    "type": "files",
                    "files": [["name": "ep1.m4a", "type": "file",
                               "file": ["url": "https://example.com/ep1.m4a"]]],
                ],
                "チャンネル": ["type": "select", "select": ["name": "R1"]],
                "放送日": ["type": "date", "date": ["start": "2026-10-18"]],
                "時間帯": ["type": "rich_text", "rich_text": [["plain_text": "05:10-05:40"]]],
                "録音時間(分)": ["type": "number", "number": NSNumber(value: 30)],
                "キーワード": ["type": "multi_select", "multi_select": [["name": "落語"]]],
            ] as [String: [String: Any]],
        ]
        let item = NotionParsing.libraryItem(
            from: page, schema: schema, mapping: DemoData.mapping, databaseID: "db-1")
        XCTAssertNotNil(item)
        XCTAssertEqual(item?.title, "テスト番組")
        XCTAssertEqual(item?.mediaFiles.map(\.name), ["ep1.m4a"])
        XCTAssertEqual(item?.propertyOrder.first, "番組名")
        let detail = item?.displayText(DemoData.mapping) ?? ""
        XCTAssertTrue(detail.contains("R1"))
    }
}

final class FormatHelpersTests: XCTestCase {
    func testMediaKind() {
        XCTAssertEqual(MediaKind(fileName: "a.M4A"), .audio)
        XCTAssertEqual(MediaKind(fileName: "b.mp4"), .video)
        XCTAssertEqual(MediaKind(fileName: "c.pdf"), .other)
        XCTAssertEqual(MediaKind(fileName: "noext"), .other)
    }

    func testClockFormat() {
        XCTAssertEqual(TimeFormat.clock(0), "0:00")
        XCTAssertEqual(TimeFormat.clock(65), "1:05")
        XCTAssertEqual(TimeFormat.clock(3723), "1:02:03")
        XCTAssertEqual(TimeFormat.clock(.nan), "0:00")
    }

    func testSanitizedFileName() {
        XCTAssertEqual(DownloadStorage.sanitized("a/b:c.m4a"), "a_b_c.m4a")
        XCTAssertEqual(DownloadStorage.sanitized(""), "download")
        XCTAssertEqual(DownloadStorage.relativePath(pageID: "p1", fileName: "x y.m4a"), "p1/x y.m4a")
    }
}
