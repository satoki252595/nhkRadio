export interface SubscriptionsPayload {
  /** 将来のマルチテナント化用。現状はオプショナル。 */
  user_id?: string;
  series_ids: string[];
  /** コーナー・キーワードで番組を捕捉 (「落語100選」「真打」など) */
  keywords?: string[];
  updated_at: string;
}

export interface SyncAdapter {
  /** リモートから購読リストを取得。未作成時は null。 */
  pull(): Promise<SubscriptionsPayload | null>;
  /** リモートへ購読リストを保存。 */
  push(payload: SubscriptionsPayload): Promise<void>;
}
