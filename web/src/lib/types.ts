export interface Series {
  series_id: string;
  series_name: string;
  service: string;
  area?: string;  // "NHK" | "JP13"(関東) | "JP27"(関西) | ""
  genre: string[];
  sample_title: string;
  sample_description: string;
  first_seen: string;
  last_seen: string;
}

export interface SeriesIndex {
  updated_at: string;
  series: Series[];
}

export interface Program {
  id: string;
  service: string;
  title: string;
  subtitle: string;
  content: string;
  start_time: string;
  end_time: string;
  duration_sec: number;
  series_id: string;
  series_name: string;
  episode_name: string;
  genre: string[];
  area?: string;
}

export interface ProgramsData {
  date: string;
  area: string;
  updated_at: string;
  programs: Program[];
}
