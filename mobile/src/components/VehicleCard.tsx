/**
 * Hero vehicle card — port of `VehicleCard` from shared.jsx.
 *
 * Blue gradient (135°) with a CSS car silhouette (now SVG), the
 * plate in mono with a translucent stroke, and a 2x2 stat grid.
 *
 * The "health %" stat is renamed to "AI оношилгоо · сүүлийн" per
 * the alignment review — backend has no health-score field, but
 * `last_ai_session_health_pct` is computed from the most recent
 * AI Mechanic session if present (otherwise hidden).
 */

import { LinearGradient } from 'expo-linear-gradient';
import { Platform, StyleSheet, View } from 'react-native';
import Svg, { Circle, Defs, Ellipse, LinearGradient as SvgGradient, Path, Rect, Stop } from 'react-native-svg';

import { useTheme } from '../theme/ThemeProvider';
import { Text } from './Text';

export type VehicleCardData = {
  plate: string;
  make: string;
  model: string;
  build_year: number;
  fuel_type?: string | null;
  steering_side?: 'LHD' | 'RHD' | string | null;
  capacity_cc?: number | null;
  engine_number?: string | null;
  mileage_km?: number | null;
  next_service_km?: number | null;
  last_ai_diagnostic_at?: string | null;
};

type Props = {
  v: VehicleCardData;
  compact?: boolean;
};

export function VehicleCard({ v, compact = false }: Props) {
  const theme = useTheme();

  const fuelLabel = v.fuel_type ? formatFuel(v.fuel_type) : '—';
  const trim = v.capacity_cc ? `${(v.capacity_cc / 1000).toFixed(1)}L` : '';
  const subline = [v.build_year, trim, fuelLabel].filter(Boolean).join(' · ');

  return (
    <View
      style={[
        styles.card,
        { borderRadius: theme.radius.lg, padding: compact ? 14 : 18 },
      ]}
    >
      <LinearGradient
        colors={['#1E3A8A', '#2563EB', '#3B82F6']}
        start={{ x: 0, y: 0 }}
        end={{ x: 1, y: 1 }}
        style={StyleSheet.absoluteFill}
      />
      <LinearGradient
        colors={['rgba(255,255,255,0.18)', 'transparent']}
        start={{ x: 0, y: 0 }}
        end={{ x: 0.5, y: 0.5 }}
        style={StyleSheet.absoluteFill}
      />

      <View style={{ flexDirection: 'row', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8 }}>
        <View style={{ flex: 1 }}>
          <Text variant="eyebrow" style={{ color: 'rgba(255,255,255,0.55)' }}>
            Миний машин
          </Text>
          <Text style={[styles.title, { color: '#fff' }]}>
            {v.make} {v.model}
          </Text>
          {subline ? (
            <Text variant="caption" style={{ color: 'rgba(255,255,255,0.7)', marginTop: 2 }}>
              {subline}
            </Text>
          ) : null}
        </View>
        <View style={styles.plateBox}>
          <Text variant="mono" weight="700" style={{ color: '#fff', letterSpacing: 1 }}>
            {v.plate}
          </Text>
        </View>
      </View>

      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 14, marginTop: compact ? 10 : 16 }}>
        <CarSilhouette w={compact ? 110 : 140} />
        <View style={{ flex: 1, flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>
          <Stat label="Гүйлт" value={v.mileage_km != null ? `${(v.mileage_km / 1000).toFixed(0)}k км` : '—'} />
          <Stat
            label="Дараагийн засвар"
            value={v.next_service_km != null ? `${v.next_service_km.toLocaleString('en-US')} км` : '—'}
          />
          <Stat label="Хөдөлгүүр" value={v.engine_number ?? '—'} />
          <Stat label="AI оношилгоо" value={v.last_ai_diagnostic_at ? formatRelative(v.last_ai_diagnostic_at) : '—'} />
        </View>
      </View>
    </View>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <View style={{ width: '47%' }}>
      <Text variant="eyebrow" style={{ color: 'rgba(255,255,255,0.6)' }}>
        {label}
      </Text>
      <Text variant="num" style={{ color: '#fff', fontSize: 13, fontWeight: '600', marginTop: 2 }}>
        {value}
      </Text>
    </View>
  );
}

function CarSilhouette({ w = 140 }: { w?: number }) {
  const h = w * 0.55;
  return (
    <Svg width={w} height={h} viewBox="0 0 140 78">
      <Defs>
        <SvgGradient id="carbody" x1="0" y1="0" x2="0" y2="1">
          <Stop offset="0" stopColor="#EAF0FF" />
          <Stop offset="1" stopColor="#9CB6F0" />
        </SvgGradient>
      </Defs>
      <Ellipse cx="70" cy="68" rx="58" ry="3" fill="rgba(0,0,0,0.25)" />
      <Path
        d="M14 56 L14 44 Q14 36 22 32 L42 22 Q52 18 70 18 Q92 18 108 26 L122 32 Q128 34 128 42 L128 56 Z"
        fill="url(#carbody)"
      />
      <Path
        d="M40 32 L48 24 Q56 22 70 22 Q86 22 96 26 L102 32 Z"
        fill="rgba(50,80,140,0.55)"
      />
      <Rect x="68" y="22" width="2" height="12" fill="rgba(50,80,140,0.7)" />
      <Circle cx="36" cy="60" r="10" fill="#0A1024" />
      <Circle cx="36" cy="60" r="5" fill="#3B4470" />
      <Circle cx="104" cy="60" r="10" fill="#0A1024" />
      <Circle cx="104" cy="60" r="5" fill="#3B4470" />
      <Rect x="118" y="40" width="6" height="6" rx="1" fill="#FFE89A" />
      <Rect x="16" y="40" width="6" height="6" rx="1" fill="#FF6E6E" />
    </Svg>
  );
}

function formatFuel(s: string): string {
  const t = s.toLowerCase();
  if (t === 'petrol' || t === 'gasoline') return 'Бензин';
  if (t === 'diesel') return 'Дизель';
  if (t === 'hybrid') return 'Хосолмол';
  if (t === 'electric') return 'Цахилгаан';
  if (t === 'lpg' || t === 'gas') return 'Хий';
  return s;
}

function formatRelative(iso: string): string {
  try {
    const ts = new Date(iso).getTime();
    const diff = Date.now() - ts;
    const mins = Math.round(diff / 60_000);
    if (mins < 1) return 'дөнгөж сая';
    if (mins < 60) return `${mins} мин`;
    const hrs = Math.round(mins / 60);
    if (hrs < 24) return `${hrs} ц`;
    const days = Math.round(hrs / 24);
    return `${days} ө`;
  } catch {
    return '—';
  }
}

const styles = StyleSheet.create({
  card: {
    overflow: 'hidden',
    shadowColor: '#1E3A8A',
    shadowOpacity: Platform.OS === 'ios' ? 0.45 : 0,
    shadowRadius: 24,
    shadowOffset: { width: 0, height: 14 },
    elevation: 6,
  },
  title: {
    fontSize: 22,
    fontWeight: '700',
    letterSpacing: -0.4,
    marginTop: 4,
  },
  plateBox: {
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: 'rgba(255,255,255,0.4)',
    borderRadius: 8,
    paddingHorizontal: 9,
    paddingVertical: 5,
    backgroundColor: 'rgba(255,255,255,0.08)',
  },
});
