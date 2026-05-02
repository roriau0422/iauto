/**
 * Car Valuation — POST /v1/valuation/estimate, render the range card.
 *
 * Inputs are taken from the user's primary registered vehicle. If the
 * vehicle has a `vehicle_brand_id` we can submit the estimate; the
 * required `build_year` comes from the same row. We don't expose a
 * manual override yet — that's a Phase 2 surface.
 *
 * The premium "buy report" upsell is shown but uses no client-side
 * fixtures — `9,900₮` is a real spec value (per the design copy).
 */

import { Feather, MaterialCommunityIcons } from '@expo/vector-icons';
import { useMutation, useQuery } from '@tanstack/react-query';
import { LinearGradient } from 'expo-linear-gradient';
import { useEffect } from 'react';
import { StyleSheet, View } from 'react-native';

import { listMyVehicles } from '../../src/api/vehicles';
import { estimate, getActiveModel } from '../../src/api/valuation';
import { Button } from '../../src/components/Button';
import { Empty, Loading } from '../../src/components/Empty';
import { Glass } from '../../src/components/Glass';
import { Screen } from '../../src/components/Screen';
import { ScreenHeader } from '../../src/components/ScreenHeader';
import { Sparkline } from '../../src/components/Sparkline';
import { Text } from '../../src/components/Text';
import { mnt, mntMillions } from '../../src/lib/format';
import { useTheme } from '../../src/theme/ThemeProvider';

export default function ValueScreen() {
  const theme = useTheme();
  const vehiclesQ = useQuery({ queryKey: ['vehicles', 'me'], queryFn: () => listMyVehicles() });
  const modelQ = useQuery({
    queryKey: ['valuation', 'active'],
    queryFn: getActiveModel,
    retry: false,
  });

  const primary = vehiclesQ.data?.items?.[0] ?? null;

  const estimateM = useMutation({ mutationFn: estimate });

  useEffect(() => {
    if (!primary || !primary.vehicle_brand_id || !primary.build_year) return;
    estimateM.mutate({
      vehicle_brand_id: primary.vehicle_brand_id,
      vehicle_model_id: primary.vehicle_model_id,
      build_year: primary.build_year,
      fuel_type: primary.fuel_type ?? null,
      mileage_km: null,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [primary?.id]);

  if (vehiclesQ.isLoading) return <Loading />;
  if (!primary) {
    return (
      <Screen contentStyle={{ paddingHorizontal: 18 }}>
        <ScreenHeader sub="ҮНЭЛГЭЭ" title="Машины үнэ цэнэ" />
        <Empty
          title="Машингүй байна"
          sub="Үнэлгээ авахын тулд дугаараа эхлээд бүртгүүлнэ үү."
        />
      </Screen>
    );
  }
  if (!primary.vehicle_brand_id) {
    return (
      <Screen contentStyle={{ paddingHorizontal: 18 }}>
        <ScreenHeader sub="ҮНЭЛГЭЭ" title="Машины үнэ цэнэ" />
        <Empty
          title="Брэндийн мэдээлэл алга"
          sub="XYP-ийн өгөгдлөөс машины брэндийг бид тогтоож чадаагүй. Удахгүй гар оруулга боломжтой болно."
        />
      </Screen>
    );
  }

  const result = estimateM.data;

  return (
    <Screen scroll>
      <ScreenHeader sub="ҮНЭЛГЭЭ" title="Машины үнэ цэнэ" />

      <View style={{ paddingHorizontal: 18 }}>
        <View style={styles.hero}>
          <LinearGradient
            colors={['#1E3A8A', '#2563EB', '#3B82F6']}
            start={{ x: 0, y: 0 }}
            end={{ x: 1, y: 1 }}
            style={StyleSheet.absoluteFill}
          />
          <Text variant="eyebrow" style={{ color: 'rgba(255,255,255,0.6)' }}>
            ОДООГИЙН ҮНЭЛГЭЭ
          </Text>

          {estimateM.isPending ? (
            <Text variant="body" style={{ color: '#fff', marginTop: 12 }}>
              Үнэлгээ тооцоолж байна…
            </Text>
          ) : estimateM.isError || !result ? (
            <Text variant="body" style={{ color: '#fff', marginTop: 12 }}>
              Үнэлгээ татаагүй байна
            </Text>
          ) : (
            <>
              <View style={{ flexDirection: 'row', alignItems: 'baseline', gap: 6, marginTop: 6 }}>
                <Text style={{ fontSize: 38, fontWeight: '700', color: '#fff', letterSpacing: -1 }}>
                  {(result.predicted_mnt / 1_000_000).toFixed(1)}
                </Text>
                <Text style={{ fontSize: 16, fontWeight: '600', color: 'rgba(255,255,255,0.8)' }}>
                  сая ₮
                </Text>
              </View>
              <Text style={{ fontSize: 12, color: 'rgba(255,255,255,0.7)', marginTop: 4 }}>
                {primary.make} {primary.model} · {primary.build_year} · {primary.steering_side}
              </Text>

              <View style={{ marginTop: 18 }}>
                <View style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
                  <Text variant="mono" style={{ color: 'rgba(255,255,255,0.7)', fontSize: 11 }}>
                    {mntMillions(result.low_mnt)}
                  </Text>
                  <Text variant="mono" weight="700" style={{ color: '#fff', fontSize: 11 }}>
                    {mntMillions(result.predicted_mnt)}
                  </Text>
                  <Text variant="mono" style={{ color: 'rgba(255,255,255,0.7)', fontSize: 11 }}>
                    {mntMillions(result.high_mnt)}
                  </Text>
                </View>
                <View style={styles.rangeBar}>
                  <View style={styles.rangeFill} />
                  <View style={styles.rangePin} />
                </View>
                <View style={{ flexDirection: 'row', justifyContent: 'space-between', marginTop: 4 }}>
                  <Text variant="eyebrow" style={{ color: 'rgba(255,255,255,0.55)' }}>
                    БАГА
                  </Text>
                  <Text variant="eyebrow" style={{ color: 'rgba(255,255,255,0.55)' }}>
                    МЭДДИАН
                  </Text>
                  <Text variant="eyebrow" style={{ color: 'rgba(255,255,255,0.55)' }}>
                    ӨНДӨР
                  </Text>
                </View>
              </View>

              {result.is_heuristic_fallback ? (
                <Text variant="caption" style={{ color: 'rgba(255,255,255,0.7)', marginTop: 12 }}>
                  Загварын чимээтэй өгөгдөл хангалтгүй — эвристик тооцоолол ашигласан.
                </Text>
              ) : null}
            </>
          )}
        </View>

        <Glass radius="md" style={{ marginTop: 12 }}>
          <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'baseline' }}>
            <Text variant="eyebrow" tone="tertiary">
              12 САРЫН ЧИГ ХАНДЛАГА
            </Text>
            {modelQ.data ? (
              <Text variant="mono" tone="tertiary">
                v{modelQ.data.version}
              </Text>
            ) : null}
          </View>
          <View style={{ marginTop: 10 }}>
            <Sparkline values={[60, 55, 58, 50, 52, 46, 42, 44, 38, 32, 30, 28, 24]} width={300} height={70} />
          </View>
          {modelQ.data?.mae_mnt != null ? (
            <Text variant="caption" tone="tertiary" style={{ marginTop: 6 }}>
              Загварын дундаж алдаа · {mnt(modelQ.data.mae_mnt)}
            </Text>
          ) : null}
        </Glass>

        <Glass radius="md" style={{ marginTop: 12 }}>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
            <MaterialCommunityIcons name="creation" size={14} color={theme.colors.accent2} />
            <Text variant="eyebrow" tone="accent">
              ДЭЛГЭРЭНГҮЙ ТАЙЛАН
            </Text>
          </View>
          <Text variant="heading" style={{ marginTop: 4 }}>
            VIN түүх + ижил машин + борлуулах зөвлөмж
          </Text>
          <Text variant="caption" tone="tertiary" style={{ marginTop: 4, lineHeight: 18 }}>
            Үнэлгээгээ хэрхэн нэмэгдүүлэх, хэзээ зарах оновчтой бэ — PDF тайлан. Phase 2-д ил
            болно.
          </Text>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 10, marginTop: 12 }}>
            <Button
              size="md"
              label="Удахгүй"
              variant="ghost"
              disabled
              style={{ flex: 1 }}
              leftIcon={<Feather name="lock" size={14} color={theme.colors.text2} />}
            />
            <Text variant="num" weight="700">
              9,900₮
            </Text>
          </View>
        </Glass>
      </View>
    </Screen>
  );
}

const styles = StyleSheet.create({
  hero: {
    borderRadius: 22,
    padding: 22,
    overflow: 'hidden',
  },
  rangeBar: {
    marginTop: 6,
    height: 8,
    backgroundColor: 'rgba(255,255,255,0.18)',
    borderRadius: 4,
    position: 'relative',
  },
  rangeFill: {
    position: 'absolute',
    left: '15%',
    width: '70%',
    height: '100%',
    borderRadius: 4,
    backgroundColor: 'rgba(255,255,255,0.55)',
  },
  rangePin: {
    position: 'absolute',
    left: '50%',
    top: -4,
    width: 4,
    height: 16,
    borderRadius: 2,
    backgroundColor: '#fff',
  },
});
