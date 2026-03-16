import { getResults, getLearning, getCalibration, getResearch, getSelfsearch, getValidation } from "@/lib/data";
import HeroMetrics from "@/components/HeroMetrics";
import LearningTimeline from "@/components/LearningTimeline";
import ExperimentLog from "@/components/ExperimentLog";
import CategoryBreakdown from "@/components/CategoryBreakdown";
import CompositeExplainer from "@/components/CompositeExplainer";
import CalibrationCurve from "@/components/CalibrationCurve";
import BucketPerformance from "@/components/BucketPerformance";
import StrategyCode from "@/components/StrategyCode";
import Methodology from "@/components/Methodology";
import ResearchOutcomes from "@/components/ResearchOutcomes";
import SelfsearchOutcomes from "@/components/SelfsearchOutcomes";
import ValidationRisks from "@/components/ValidationRisks";
import type { ValidationData } from "@/components/ValidationRisks";

function Section({
  title,
  desc,
  children,
}: {
  title: string;
  desc: string;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold text-white">{title}</h2>
        <p className="text-sm text-zinc-500">{desc}</p>
      </div>
      {children}
    </section>
  );
}

export default function Home() {
  const results = getResults();
  const learning = getLearning();
  const calibration = getCalibration();
  const research = getResearch();
  const selfsearch = getSelfsearch();
  const validation = getValidation() as ValidationData;

  return (
    <main className="mx-auto max-w-7xl space-y-16 px-6 py-12">
      <Section title="Validation Results" desc="Top-line performance on held-out validation set (36K markets)">
        <HeroMetrics v={learning.validation} testV={learning.test} categoryStates={learning.category_states} />
      </Section>

      <Section title="Learning Timeline" desc="Best composite score per category across 50 iterations of autonomous tuning">
        <LearningTimeline rows={results} />
      </Section>

      <Section title="Composite Score Formula" desc="How the three components combine into a single optimization target">
        <CompositeExplainer v={learning.validation} categoryStates={learning.category_states} />
      </Section>

      <Section title="Experiment Log" desc={`All ${results.length} experiments: parameter changes, outcomes, and keep/discard decisions`}>
        <ExperimentLog rows={results} />
      </Section>

      <Section title="Category Breakdown" desc="Per-category performance and optimized parameters after learning">
        <CategoryBreakdown states={learning.category_states} />
      </Section>

      <Section title="Perception vs Reality" desc="The core insight: market prices vs actual outcomes across 180K markets, verified across 3 independent time periods">
        <CalibrationCurve buckets={calibration.buckets} splitBuckets={calibration.perception_vs_reality_by_split} />
      </Section>

      <Section title="Expiry Analysis" desc="How time-to-expiry affects market calibration and mispricing edge">
        <ResearchOutcomes research={research} />
      </Section>

      <Section title="LLM vs Market Study" desc="Information advantage: LLM speed vs market efficiency on event-driven predictions">
        <SelfsearchOutcomes data={selfsearch} />
      </Section>

      <Section title="Validation & Risks" desc="Parameter transfer gaps, temporal drift detection, and confidence intervals for calibration reliability">
        <ValidationRisks data={validation} />
      </Section>

      <Section title="Bucket Performance" desc="Per-bucket calibration data with category drill-down">
        <BucketPerformance
          buckets={calibration.buckets}
          categoryBuckets={calibration.category_buckets}
        />
      </Section>

      <Section title="Strategy Logic" desc="The decision code the learning loop optimizes, with tunable parameters">
        <StrategyCode />
      </Section>

      <Section title="Methodology" desc="Data sourcing, sampling, and statistical approach">
        <Methodology
          methodology={calibration.methodology}
          totalMarkets={calibration.total_markets}
          splitCounts={calibration.split_counts}
        />
      </Section>
    </main>
  );
}
