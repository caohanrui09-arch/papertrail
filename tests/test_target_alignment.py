"""Exercise raw targets, real Trainer updates, and the predeclared dev gate."""
import tempfile
from pathlib import Path
import unittest

import torch
from transformers import (AutoTokenizer, DataCollatorForSeq2Seq, Seq2SeqTrainingArguments,
                          T5Config, T5ForConditionalGeneration)

from gsearch.benchmark_target_alignment import gate
from gsearch.train_target_alignment import (AlignedDataset, AuditCollator, BASE,
                                            OrderedSeq2SeqTrainer, TARGETS, read)


class AlignmentTests(unittest.TestCase):
    def test_raw_unstable_aliases_preserved(self) -> None:
        if not (TARGETS / "common.json").exists():
            self.skipTest("prepare frozen targets first")
        common = read(TARGETS / "common.json")
        aliases = read(TARGETS / "short.json")["aliases"]
        tokenizer = AutoTokenizer.from_pretrained(BASE, local_files_only=True)
        unstable = {r["doc_id"]: r for r in aliases if
                    tokenizer.encode(tokenizer.decode(r["token_ids"], skip_special_tokens=True),
                                     add_special_tokens=False)+[tokenizer.eos_token_id] != r["token_ids"]}
        self.assertEqual(len(unstable), 197)
        dataset = AlignedDataset(common, aliases)
        tested = set()
        for i, example_index in enumerate(common["schedule"]):
            doc_id = common["examples"][example_index]["doc_id"]
            if doc_id in unstable:
                self.assertEqual(dataset[i]["labels"], unstable[doc_id]["token_ids"])
                tested.add(doc_id)
        self.assertGreater(len(tested), 180)

    def test_real_trainer_uses_frozen_order_and_updates(self) -> None:
        tokenizer = AutoTokenizer.from_pretrained(BASE, local_files_only=True)
        common = {"examples": [{"input_ids": [4, 5, 1], "attention_mask": [1, 1, 1], "doc_id": "a"},
                                {"input_ids": [6, 1], "attention_mask": [1, 1], "doc_id": "b"}],
                  "schedule": [1, 0, 1, 1]}
        dataset = AlignedDataset(common, [{"doc_id": "a", "token_ids": [7, 8, 1]},
                                          {"doc_id": "b", "token_ids": [9, 1]}])
        model = T5ForConditionalGeneration(T5Config(vocab_size=64, d_model=16, d_ff=32,
                        num_layers=1, num_decoder_layers=1, num_heads=2, d_kv=8,
                        decoder_start_token_id=0, pad_token_id=0, eos_token_id=1))
        before = model.shared.weight.detach().clone()
        collator = AuditCollator(DataCollatorForSeq2Seq(tokenizer, model=model))
        torch.set_num_threads(2)
        with tempfile.TemporaryDirectory() as tmp:
            args = Seq2SeqTrainingArguments(output_dir=tmp, max_steps=2, per_device_train_batch_size=2,
                use_cpu=True, save_strategy="no", eval_strategy="no", report_to="none", disable_tqdm=True,
                remove_unused_columns=False, dataloader_pin_memory=False, lr_scheduler_type="constant")
            optimizer = torch.optim.AdamW(model.parameters(), lr=0.001, weight_decay=0.01)
            trainer = OrderedSeq2SeqTrainer(model=model, args=args, train_dataset=dataset,
                      processing_class=tokenizer, data_collator=collator, optimizers=(optimizer, None))
            trainer.model_accepts_loss_kwargs = False
            trainer.train()
            self.assertEqual((trainer.state.global_step, collator.positions, collator.batches), (2, 4, 2))
        self.assertFalse(torch.equal(before, model.shared.weight.detach()))
        self.assertEqual(collator.usage["label_tokens"], 9)
        self.assertEqual(collator.usage["padded_label_tokens"], 10)

    def test_collator_rejects_shuffling(self) -> None:
        collator = AuditCollator(None)
        with self.assertRaises(ValueError):
            collator([{"_position": 1}])

    def test_gate_cost_cannot_excuse_quality_collapse(self) -> None:
        def result(ndcg: float, recall: float, uncovered: float, tokens: float, seconds: float) -> dict:
            return {"queries": [{"claim_id": 1}], "summary": {"ndcg@10": ndcg, "recall@10": recall,
                "mean_seconds": seconds}, "groups": {"some_gold_not_supervised": {"recall": uncovered}},
                "cost": {"mean_returned_tokens": tokens}}
        full = result(0.5, 0.6, 0.1, 16, 1)
        self.assertFalse(gate(full, result(0.1, 0.2, 0, 4, 0.4))["passed"])
        self.assertTrue(gate(full, result(0.5, 0.6, 0.1, 4, 0.4))["cost_route_passed"])
        self.assertTrue(gate(full, result(0.52, 0.6, 0.1, 16, 1))["quality_route_passed"])
        self.assertFalse(gate(full, result(0.52, 0.6, 0.05, 4, 0.4))["passed"])


if __name__ == "__main__":
    unittest.main()
