export interface ServerTier {
  name: string;
  provider: "AWS" | "Hetzner" | "DO";
  vcpu: number;
  ramGB: number;
  monthlyUsd: number;
}

export const SERVER_TIERS: ServerTier[] = [
  { name: "t3.medium",  provider: "AWS",     vcpu: 2,  ramGB: 4,   monthlyUsd: 30  },
  { name: "t3.large",   provider: "AWS",     vcpu: 2,  ramGB: 8,   monthlyUsd: 60  },
  { name: "c6i.xlarge", provider: "AWS",     vcpu: 4,  ramGB: 8,   monthlyUsd: 122 },
  { name: "c6i.2xlarge",provider: "AWS",     vcpu: 8,  ramGB: 16,  monthlyUsd: 244 },
  { name: "CPX21",      provider: "Hetzner", vcpu: 3,  ramGB: 4,   monthlyUsd: 9   },
  { name: "CPX31",      provider: "Hetzner", vcpu: 4,  ramGB: 8,   monthlyUsd: 17  },
  { name: "CPX41",      provider: "Hetzner", vcpu: 8,  ramGB: 16,  monthlyUsd: 30  },
  { name: "CPX51",      provider: "Hetzner", vcpu: 16, ramGB: 32,  monthlyUsd: 57  },
  { name: "Premium-4",  provider: "DO",      vcpu: 4,  ramGB: 8,   monthlyUsd: 48  },
  { name: "Premium-8",  provider: "DO",      vcpu: 8,  ramGB: 16,  monthlyUsd: 96  },
  { name: "Premium-16", provider: "DO",      vcpu: 16, ramGB: 32,  monthlyUsd: 192 },
];

export function recommend(requiredCores: number, peakRamMb: number): ServerTier[] {
  const peakRamGB = peakRamMb / 1024;
  const eligible = SERVER_TIERS.filter(
    (t) => t.vcpu >= requiredCores && t.ramGB >= peakRamGB,
  ).sort((a, b) => a.monthlyUsd - b.monthlyUsd);

  // one per provider
  const seen = new Set<string>();
  return eligible.filter((t) => {
    if (seen.has(t.provider)) return false;
    seen.add(t.provider);
    return true;
  });
}
