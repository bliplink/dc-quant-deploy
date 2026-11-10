import unittest

from recovery.promote_qualified_catalog_candidates import reviewed_independent_candidates


class SemanticReleaseReviewTest(unittest.TestCase):
    def record(self, name='candidate'):
        return {'strategy': name, 'symbol': 'BTCUSDT', 'scene': 'trend', 'source_sha256': 'frozen-source'}

    def review(self, name='candidate'):
        return {**self.record(name), 'decision': 'APPROVE', 'mechanism_id': 'completed_auction_acceptance',
                'reviewer': 'local_codex', 'rationale': 'Original event mechanism and exit-only version reviewed separately.',
                'active_peers': []}

    def run_review(self, records, reviews, peers=()):
        return reviewed_independent_candidates(records, {
            'schema': 'independent_mechanism_review_v1', 'reviews': reviews}, peers)

    def test_missing_review_defers_instead_of_submitting_or_relabelling_as_financial_failure(self):
        approved, deferred = self.run_review([self.record()], [])
        self.assertEqual([], approved)
        self.assertEqual(1, len(deferred))

    def test_frozen_source_scope_and_substantive_mechanism_are_required(self):
        for key, value in [('source_sha256', 'changed'), ('scene', 'range'),
                           ('symbol', 'ETHUSDT'), ('rationale', ''), ('mechanism_id', '')]:
            approved, deferred = self.run_review([self.record()], [{**self.review(), key: value}])
            self.assertEqual([], approved, key)
            self.assertEqual(1, len(deferred))
        approved, deferred = self.run_review([self.record()], [self.review()])
        self.assertEqual([self.record()], approved)
        self.assertEqual([], deferred)

    def test_same_cell_same_mechanism_is_not_two_independent_strategies(self):
        records = [self.record('first'), self.record('second')]
        approved, deferred = self.run_review(records, [self.review('first'), self.review('second')])
        self.assertEqual(['first'], [row['strategy'] for row in approved])
        self.assertEqual(1, len(deferred))

    def test_predeclared_group_cannot_be_relabelled_to_count_a_variant_twice(self):
        records = [{**self.record(name), 'mechanism_group': 'wilder_adx_directional_breakout'}
                   for name in ('first', 'second')]
        reviews = [{**self.review('first'), 'mechanism_id': 'wilder_adx_directional_breakout'},
                   {**self.review('second'), 'mechanism_id': 'wilder_adx_selective_variant'}]
        approved, deferred = self.run_review(records, reviews)
        self.assertEqual(['first'], [row['strategy'] for row in approved])
        self.assertIn('predeclared', deferred[0]['reason'])
        reviews[1]['mechanism_id'] = 'wilder_adx_directional_breakout'
        approved, deferred = self.run_review(records, reviews)
        self.assertEqual(['first'], [row['strategy'] for row in approved])
        self.assertIn('same reviewed mechanism', deferred[0]['reason'])

    def test_changed_active_peers_require_a_fresh_explicit_comparison(self):
        peer = {'strategy_name': 'active', 'strategy_version': 'v2', 'reason': 'qualified',
                'symbol_scope': 'BTCUSDT', 'scene': 'trend'}
        self.assertEqual([], self.run_review([self.record()], [self.review()], [peer])[0])
        review = {**self.review(), 'active_peers': ['active@v2']}
        self.assertEqual([], self.run_review([self.record()], [review], [peer])[0])
        review['peer_comparisons'] = {'active@v2': 'Different causal entry mechanism; not a parameter or exit-only clone.'}
        self.assertEqual([self.record()], self.run_review([self.record()], [review], [peer])[0])

    def test_duplicate_review_identities_fail_closed(self):
        with self.assertRaises(ValueError):
            self.run_review([self.record()], [self.review(), self.review()])


if __name__ == '__main__':
    unittest.main()
