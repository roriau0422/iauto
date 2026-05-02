/**
 * Onboarding step 5 — vehicle reveal. Pulls the freshly-registered car
 * via `GET /v1/vehicles/{id}` and renders the hero card + tech-passport
 * detail grid.
 */

import { Feather } from '@expo/vector-icons';
import { useQuery } from '@tanstack/react-query';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { StyleSheet, View } from 'react-native';

import { getVehicle } from '../../src/api/vehicles';
import { Button } from '../../src/components/Button';
import { Empty, ErrorState, Loading } from '../../src/components/Empty';
import { Glass } from '../../src/components/Glass';
import { Screen } from '../../src/components/Screen';
import { Text } from '../../src/components/Text';
import { VehicleCard } from '../../src/components/VehicleCard';
import { fuelLabelMn } from '../../src/lib/format';
import { useTheme } from '../../src/theme/ThemeProvider';

export default function RevealScreen() {
  const theme = useTheme();
  const router = useRouter();
  const { vehicle_id } = useLocalSearchParams<{ vehicle_id?: string }>();

  const q = useQuery({
    queryKey: ['vehicle', vehicle_id],
    queryFn: () => {
      if (!vehicle_id) throw new Error('missing vehicle id');
      return getVehicle(vehicle_id);
    },
    enabled: !!vehicle_id,
  });

  if (q.isLoading || !vehicle_id) {
    return (
      <Screen contentStyle={{ paddingHorizontal: 18 }}>
        <Loading label="Машины мэдээлэл татаж байна" />
      </Screen>
    );
  }
  if (q.isError) {
    return (
      <Screen contentStyle={{ paddingHorizontal: 18 }}>
        <ErrorState title="Алдаа гарлаа" sub="Машины мэдээллийг татаж чадсангүй." />
      </Screen>
    );
  }
  const v = q.data;
  if (!v) {
    return (
      <Screen contentStyle={{ paddingHorizontal: 18 }}>
        <Empty title="Машин олдсонгүй" />
      </Screen>
    );
  }

  const passport: [string, string][] = [
    ['VIN', v.vin ?? '—'],
    ['Хөдөлгүүр', v.engine_number ?? '—'],
    ['Багтаамж', v.capacity_cc ? `${v.capacity_cc} cc` : '—'],
    ['Өнгө', v.color ?? '—'],
    ['Жолооны тал', v.steering_side ?? '—'],
    ['Импорт', v.import_month ?? '—'],
    ['Шатахуун', fuelLabelMn(v.fuel_type)],
    ['Үйлдвэрлэсэн он', v.build_year ? String(v.build_year) : '—'],
  ];

  return (
    <Screen scroll contentStyle={{ paddingHorizontal: 18 }}>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 10, paddingVertical: 18 }}>
        <View
          style={{
            width: 28,
            height: 28,
            borderRadius: 14,
            backgroundColor: 'rgba(94,226,160,0.18)',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          <Feather name="check" size={16} color={theme.colors.success} />
        </View>
        <Text variant="body" weight="600">
          Бүртгэлд олдлоо
        </Text>
      </View>

      <VehicleCard
        v={{
          plate: v.plate,
          make: v.make ?? 'Машин',
          model: v.model ?? '',
          build_year: v.build_year ?? new Date().getFullYear(),
          fuel_type: v.fuel_type,
          steering_side: v.steering_side,
          capacity_cc: v.capacity_cc,
          engine_number: v.engine_number,
        }}
      />

      <Glass radius="md" style={{ marginTop: 12 }}>
        <Text variant="eyebrow" tone="tertiary" style={{ marginBottom: 10 }}>
          Техникийн пасспорт
        </Text>
        <View style={styles.grid}>
          {passport.map(([k, val]) => (
            <View key={k} style={styles.cell}>
              <Text variant="eyebrow" tone="tertiary">
                {k}
              </Text>
              <Text variant="mono" style={{ marginTop: 2 }}>
                {val}
              </Text>
            </View>
          ))}
        </View>
      </Glass>

      <Button
        size="lg"
        label="Энэ миний машин · үргэлжлүүлэх"
        onPress={() => router.replace('/(driver)')}
        style={{ marginTop: 18 }}
      />
      <Button
        variant="ghost"
        size="md"
        label="Өөр машин нэмэх"
        onPress={() => router.replace('/onboarding/plate')}
        style={{ marginTop: 8 }}
      />
    </Screen>
  );
}

const styles = StyleSheet.create({
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  cell: { width: '48%', paddingVertical: 6 },
});
