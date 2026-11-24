import unittest

import torch
from torch.nn import functional as F


class NativeAmpLossChecks(unittest.TestCase):
    def test_amp_unreduced_mean_matches_amp_native_reduction(self):
        torch.manual_seed(19)
        logits=torch.randn(8,5,32303,device='cuda').to(torch.bfloat16)
        labels=torch.randint(0,32303,(8,5),device='cuda')
        with torch.inference_mode(),torch.autocast('cuda',dtype=torch.bfloat16):
            mean=F.cross_entropy(logits.reshape(-1,32303),labels.reshape(-1))
            values=F.cross_entropy(logits.reshape(-1,32303),labels.reshape(-1),reduction='none')
        self.assertLess(abs(float(mean)-float(values.float().mean())),1e-4)

    def test_fp32_analysis_mean_matches_fp32_native_reduction(self):
        torch.manual_seed(20)
        logits=torch.randn(8,5,32303,device='cuda').to(torch.bfloat16).float()
        labels=torch.randint(0,32303,(8,5),device='cuda')
        with torch.inference_mode():
            mean=F.cross_entropy(logits.reshape(-1,32303),labels.reshape(-1))
            values=F.cross_entropy(logits.reshape(-1,32303),labels.reshape(-1),reduction='none')
        self.assertLess(abs(float(mean)-float(values.mean())),1e-5)


if __name__=='__main__':unittest.main()
