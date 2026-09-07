/**
 * Aeon's End Card schema representing supply cards (Gems, Relics, Spells)
 * loaded from canonical card data or detected from image scans.
 */
export interface Card {
  /** Canonical array index (0 to N-1) in the supply cards database */
  index: number;
  /** Unique card identifier code (e.g. 'DiamondCluster', 'AB33') */
  id: string;
  /** Display title of the supply card */
  name: string;
  /** Card classification (e.g., 'Gem', 'Relic', or 'Spell') */
  type: string;
  /** Aether purchase cost */
  cost: string | number;
  /** Rules text effect, containing formatting tags like <b> or <span class="aether"> */
  effect: string;
  /** Source expansion or set (e.g. 'Aeons End', 'War Eternal', 'The New Age') */
  expansion: string;
}

