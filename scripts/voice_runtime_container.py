#!/usr/bin/env python3
from __future__ import annotations

from voice_asr_backend import LocalASRBackend, create_local_asr_backend
from voice_assembly_controller import AssemblyController
from voice_massage_controller import MassageController
from voice_online_services import OnlineServices
from voice_dialogue_backend import DifyWorkflowBackend
from voice_robot_executor import ROSRobotExecutor
from voice_text_pipeline import process_text
from voice_tts_backend import LocalTTSBackend, create_local_tts_backend
from voice_runtime_config import robot_commands_enabled


class VoiceRuntimeContainer:
    def __init__(self, asr=None, tts=None, dialogue=None, executor=None, assembly_controller=None, massage_controller=None, online_services=None):
        self.asr_backend = asr
        self.tts_backend = tts
        self.dialogue_backend = dialogue
        self.executor = executor
        self.robot_executor = executor
        self.assembly_controller = assembly_controller if assembly_controller is not None else AssemblyController()
        self.massage_controller = massage_controller if massage_controller is not None else MassageController()
        self.online_services = online_services if online_services is not None else OnlineServices()

    @classmethod
    def from_local(cls, recognizer=None, speaker=None, executor=None, dialogue=None, assembly_controller=None, massage_controller=None, online_services=None):
        asr = LocalASRBackend(recognizer) if recognizer is not None else create_local_asr_backend()
        tts = LocalTTSBackend(speaker) if speaker is not None else create_local_tts_backend()
        return cls(
            asr=asr,
            tts=tts,
            dialogue=dialogue or DifyWorkflowBackend(),
            executor=executor,
            assembly_controller=assembly_controller,
            massage_controller=massage_controller,
            online_services=online_services,
        )

    @classmethod
    def from_config(cls):
        enabled = robot_commands_enabled()
        executor = ROSRobotExecutor() if enabled else None
        if enabled:
            print(
                "⚠️ 实机兼容控制已启用：本包不提供位移/角度/工作空间护栏；"
                "外部 ROS 控制器和实体急停必须有效。",
                flush=True,
            )
        return cls(
            asr=create_local_asr_backend(),
            tts=create_local_tts_backend(),
            dialogue=DifyWorkflowBackend(),
            executor=executor,
            assembly_controller=AssemblyController(),
            massage_controller=MassageController(),
            online_services=OnlineServices(),
        )

    def initialize(self) -> None:
        if self.asr_backend is None:
            raise RuntimeError("ASR backend is required")
        initialize_asr = getattr(self.asr_backend, "initialize", None)
        if callable(initialize_asr):
            initialize_asr()
        if self.executor is not None:
            initialize_executor = getattr(self.executor, "initialize", None)
            if callable(initialize_executor):
                initialize_executor()
        # Hide Kokoro cold start (~6s load+warmup) behind idle wake listening.
        # speak() still blocks on initialize() if the user talks before ready.
        tts = self.tts_backend
        if tts is not None:
            start_preload = getattr(tts, "start_preload", None)
            if callable(start_preload):
                start_preload()
            else:
                initialize_tts = getattr(tts, "initialize", None)
                if callable(initialize_tts):
                    import threading

                    threading.Thread(
                        target=initialize_tts,
                        name="tts-preload",
                        daemon=True,
                    ).start()

    @property
    def wake_asr_model(self):
        initialize = getattr(self.asr_backend, "initialize", None)
        if callable(initialize):
            initialize()
        model = getattr(self.asr_backend, "model", None)
        if model is None:
            raise RuntimeError("the selected ASR backend cannot drive ASR wake-word mode")
        return model

    def recognize(self, samples, sample_rate):
        return self.asr_backend.transcribe(samples, sample_rate)

    def speak(self, text):
        if self.tts_backend is None:
            return False
        return self.tts_backend.speak(text)

    def handle_text(self, text, reply_speaker=None, tracker=None):
        return process_text(
            text,
            executor=self.executor,
            speaker=reply_speaker or self.speak,
            dialogue=self.dialogue_backend,
            runtime=self,
            tracker=tracker,
            assembly_controller=self.assembly_controller,
            massage_controller=self.massage_controller,
            online_services=self.online_services,
        )

    def close(self) -> None:
        for component in (
            self.massage_controller,
            self.online_services,
            self.assembly_controller,
            self.executor,
            self.tts_backend,
            self.asr_backend,
            self.dialogue_backend,
        ):
            close = getattr(component, "close", None)
            if callable(close):
                close()
