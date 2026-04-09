/**
 * JST (Asia/Tokyo) 固定の日時表示ヘルパー。
 *
 * 番組データの ISO 文字列は +09:00 オフセット付きで JST 時刻を表すが、
 * ブラウザの Date API は標準で **ローカルタイムゾーン** の値を返すため、
 * JST 以外の環境では表示時刻がズレる。
 *
 * このモジュールは Intl.DateTimeFormat に timeZone: 'Asia/Tokyo' を明示し、
 * 曜日は数値計算で求めることで、どの環境でも常に JST で表示する。
 */

const TZ = 'Asia/Tokyo';
const WEEKDAYS = ['日', '月', '火', '水', '木', '金', '土'] as const;

interface JstParts {
  year: number;
  month: number;
  day: number;
  hour: number;
  minute: number;
  /** 曜日 (1文字: 日/月/火/水/木/金/土) */
  weekday: string;
}

/** ISO 文字列を JST に変換し、各フィールドを取り出す。 */
export function jstParts(iso: string): JstParts {
  const d = new Date(iso);
  // en-CA は ISO 形式 (YYYY-MM-DD HH:mm) 風で安定
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: TZ,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
    hourCycle: 'h23',
  }).formatToParts(d);
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? '0';
  const year = Number(get('year'));
  const month = Number(get('month'));
  const day = Number(get('day'));
  const hour = Number(get('hour'));
  const minute = Number(get('minute'));
  // 曜日: JST 日付の Y/M/D を UTC として再構築 → getUTCDay() で安定計算
  const weekday = WEEKDAYS[new Date(Date.UTC(year, month - 1, day)).getUTCDay()];
  return { year, month, day, hour, minute, weekday };
}

/** ISO → 'HH:MM' (JST) */
export function fmtJstTime(iso: string): string {
  const p = jstParts(iso);
  return `${String(p.hour).padStart(2, '0')}:${String(p.minute).padStart(2, '0')}`;
}

/** ISO → 'M/D(曜)' (JST) */
export function fmtJstDate(iso: string): string {
  const p = jstParts(iso);
  return `${p.month}/${p.day}(${p.weekday})`;
}

/** ISO → 'M/D(曜) HH:MM' (JST) */
export function fmtJstDateTime(iso: string): string {
  const p = jstParts(iso);
  const hour = String(p.hour).padStart(2, '0');
  const minute = String(p.minute).padStart(2, '0');
  return `${p.month}/${p.day}(${p.weekday}) ${hour}:${minute}`;
}

/** 'YYYY-MM-DD' (JST 日付文字列) → 'M/D(曜)' (JST) */
export function fmtJstDateOnly(dateStr: string): string {
  return fmtJstDate(`${dateStr}T00:00:00+09:00`);
}
