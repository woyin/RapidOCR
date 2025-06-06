# -*- encoding: utf-8 -*-
# @Author: SWHL
# @Contact: liekkaskono@163.com
import os
import platform
import traceback
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
from onnxruntime import (
    GraphOptimizationLevel,
    InferenceSession,
    SessionOptions,
    get_available_providers,
    get_device,
)

from ..utils import DownloadFile, DownloadFileInput
from ..utils.logger import Logger
from .base import FileInfo, InferSession


class EP(Enum):
    CPU_EP = "CPUExecutionProvider"
    CUDA_EP = "CUDAExecutionProvider"
    DIRECTML_EP = "DmlExecutionProvider"


class OrtInferSession(InferSession):
    def __init__(self, cfg: Dict[str, Any]):
        self.logger = Logger(logger_name=__name__).get_log()

        model_path = cfg.get("model_path", None)
        if model_path is None:
            # 说明用户没有指定自己模型，使用默认模型
            model_info = self.get_model_url(
                FileInfo(
                    engine_type=cfg.engine_type,
                    ocr_version=cfg.ocr_version,
                    task_type=cfg.task_type,
                    lang_type=cfg.lang_type,
                    model_type=cfg.model_type,
                )
            )
            model_path = self.DEFAULT_MODEL_PATH / Path(model_info["model_dir"]).name
            download_params = DownloadFileInput(
                file_url=model_info["model_dir"],
                sha256=model_info["SHA256"],
                save_path=model_path,
                logger=self.logger,
            )
            DownloadFile.run(download_params)

        self.logger.info(f"Using {model_path}")
        model_path = Path(model_path)
        self._verify_model(model_path)

        self.cfg_use_cuda = cfg.engine_cfg.get("use_cuda", None)
        self.cfg_use_dml = cfg.engine_cfg.get("use_dml", None)

        self.had_providers: List[str] = get_available_providers()
        EP_list = self._get_ep_list()

        sess_opt = self._init_sess_opts(cfg.engine_cfg)
        self.session = InferenceSession(
            model_path,
            sess_options=sess_opt,
            providers=EP_list,
        )
        self._verify_providers()

    @staticmethod
    def _init_sess_opts(cfg: Dict[str, Any]) -> SessionOptions:
        sess_opt = SessionOptions()
        sess_opt.log_severity_level = 4
        sess_opt.enable_cpu_mem_arena = cfg.enable_cpu_mem_arena
        sess_opt.graph_optimization_level = GraphOptimizationLevel.ORT_ENABLE_ALL

        cpu_nums = os.cpu_count()
        intra_op_num_threads = cfg.get("intra_op_num_threads", -1)
        if intra_op_num_threads != -1 and 1 <= intra_op_num_threads <= cpu_nums:
            sess_opt.intra_op_num_threads = intra_op_num_threads

        inter_op_num_threads = cfg.get("inter_op_num_threads", -1)
        if inter_op_num_threads != -1 and 1 <= inter_op_num_threads <= cpu_nums:
            sess_opt.inter_op_num_threads = inter_op_num_threads

        return sess_opt

    def _get_ep_list(self) -> List[Tuple[str, Dict[str, Any]]]:
        cpu_provider_opts = {
            "arena_extend_strategy": "kSameAsRequested",
        }
        EP_list = [(EP.CPU_EP.value, cpu_provider_opts)]

        cuda_provider_opts = {
            "device_id": 0,
            "arena_extend_strategy": "kNextPowerOfTwo",
            "cudnn_conv_algo_search": "EXHAUSTIVE",
            "do_copy_in_default_stream": True,
        }
        self.use_cuda = self._check_cuda()
        if self.use_cuda:
            EP_list.insert(0, (EP.CUDA_EP.value, cuda_provider_opts))

        self.use_directml = self._check_dml()
        if self.use_directml:
            self.logger.info(
                "Windows 10 or above detected, try to use DirectML as primary provider"
            )
            directml_options = (
                cuda_provider_opts if self.use_cuda else cpu_provider_opts
            )
            EP_list.insert(0, (EP.DIRECTML_EP.value, directml_options))
        return EP_list

    def _check_cuda(self) -> bool:
        if not self.cfg_use_cuda:
            return False

        cur_device = get_device()
        if cur_device == "GPU" and EP.CUDA_EP.value in self.had_providers:
            return True

        self.logger.warning(
            "%s is not in available providers (%s). Use %s inference by default.",
            EP.CUDA_EP.value,
            self.had_providers,
            self.had_providers[0],
        )
        self.logger.info("!!!Recommend to use rapidocr_paddle for inference on GPU.")
        self.logger.info(
            "(For reference only) If you want to use GPU acceleration, you must do:"
        )
        self.logger.info(
            "First, uninstall all onnxruntime pakcages in current environment."
        )
        self.logger.info(
            "Second, install onnxruntime-gpu by `pip install onnxruntime-gpu`."
        )
        self.logger.info(
            "\tNote the onnxruntime-gpu version must match your cuda and cudnn version."
        )
        self.logger.info(
            "\tYou can refer this link: https://onnxruntime.ai/docs/execution-providers/CUDA-EP.html"
        )
        self.logger.info(
            "Third, ensure %s is in available providers list. e.g. ['CUDAExecutionProvider', 'CPUExecutionProvider']",
            EP.CUDA_EP.value,
        )
        return False

    def _check_dml(self) -> bool:
        if not self.cfg_use_dml:
            return False

        cur_os = platform.system()
        if cur_os != "Windows":
            self.logger.warning(
                "DirectML is only supported in Windows OS. The current OS is %s. Use %s inference by default.",
                cur_os,
                self.had_providers[0],
            )
            return False

        window_build_number_str = platform.version().split(".")[-1]
        window_build_number = (
            int(window_build_number_str) if window_build_number_str.isdigit() else 0
        )

        if window_build_number < 18362:
            self.logger.warning(
                "DirectML is only supported in Windows 10 Build 18362 and above OS. The current Windows Build is %s. Use %s inference by default.",
                window_build_number,
                self.had_providers[0],
            )
            return False

        if EP.DIRECTML_EP.value in self.had_providers:
            return True

        self.logger.warning(
            "%s is not in available providers (%s). Use %s inference by default.",
            EP.DIRECTML_EP.value,
            self.had_providers,
            self.had_providers[0],
        )
        self.logger.info("If you want to use DirectML acceleration, you must do:")
        self.logger.info(
            "First, uninstall all onnxruntime pakcages in current environment."
        )
        self.logger.info(
            "Second, install onnxruntime-directml by `pip install onnxruntime-directml`"
        )
        self.logger.info(
            "Third, ensure %s is in available providers list. e.g. ['DmlExecutionProvider', 'CPUExecutionProvider']",
            EP.DIRECTML_EP.value,
        )
        return False

    def _verify_providers(self):
        session_providers = self.session.get_providers()
        first_provider = session_providers[0]

        if self.use_cuda and first_provider != EP.CUDA_EP.value:
            self.logger.warning(
                "%s is not avaiable for current env, the inference part is automatically shifted to be executed under %s.",
                EP.CUDA_EP.value,
                first_provider,
            )

        if self.use_directml and first_provider != EP.DIRECTML_EP.value:
            self.logger.warning(
                "%s is not available for current env, the inference part is automatically shifted to be executed under %s.",
                EP.DIRECTML_EP.value,
                first_provider,
            )

    def __call__(self, input_content: np.ndarray) -> np.ndarray:
        input_dict = dict(zip(self.get_input_names(), [input_content]))
        try:
            return self.session.run(self.get_output_names(), input_dict)[0]
        except Exception as e:
            error_info = traceback.format_exc()
            raise ONNXRuntimeError(error_info) from e

    def get_input_names(self) -> List[str]:
        return [v.name for v in self.session.get_inputs()]

    def get_output_names(self) -> List[str]:
        return [v.name for v in self.session.get_outputs()]

    def get_character_list(self, key: str = "character") -> List[str]:
        meta_dict = self.session.get_modelmeta().custom_metadata_map
        return meta_dict[key].splitlines()

    def have_key(self, key: str = "character") -> bool:
        meta_dict = self.session.get_modelmeta().custom_metadata_map
        if key in meta_dict.keys():
            return True
        return False


class ONNXRuntimeError(Exception):
    pass
