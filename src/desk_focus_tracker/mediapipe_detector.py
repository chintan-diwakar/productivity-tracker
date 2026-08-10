from __future__ import annotations

from types import ModuleType
from typing import Any

from desk_focus_tracker.camera import DependencyError, import_cv2
from desk_focus_tracker.config import AppConfig
from desk_focus_tracker.domain import DetectionResult
from desk_focus_tracker.models import (
    FACE_LANDMARKER_MODEL,
    HAND_LANDMARKER_MODEL,
    MODEL_SET_VERSION,
    OBJECT_DETECTOR_MODEL,
    ModelStore,
)
from desk_focus_tracker.vision import (
    BehaviorClassifier,
    NormalizedBox,
    Point,
    VisionEvidence,
    pitch_degrees_from_transformation_matrix,
)


def import_mediapipe() -> ModuleType:
    try:
        import mediapipe
    except ImportError as error:
        raise DependencyError(
            "MediaPipe is not installed. Install the project with: python -m pip install -e ."
        ) from error
    return mediapipe


class MediaPipeDetector:
    model_version = MODEL_SET_VERSION

    def __init__(self, config: AppConfig) -> None:
        store = ModelStore(config.model_dir)
        store.require_all()

        self._mp = import_mediapipe()
        self._cv2 = import_cv2()
        self._closed = False
        self._hand_landmarker: Any | None = None
        running_mode = self._mp.tasks.vision.RunningMode.IMAGE
        base_options = self._mp.tasks.BaseOptions

        object_options = self._mp.tasks.vision.ObjectDetectorOptions(
            base_options=base_options(
                model_asset_path=str(store.path_for(OBJECT_DETECTOR_MODEL)),
            ),
            running_mode=running_mode,
            max_results=5,
            score_threshold=config.object_score_threshold,
            category_allowlist=["person", "cell phone"],
        )
        face_options = self._mp.tasks.vision.FaceLandmarkerOptions(
            base_options=base_options(
                model_asset_path=str(store.path_for(FACE_LANDMARKER_MODEL)),
            ),
            running_mode=running_mode,
            num_faces=2,
            output_face_blendshapes=False,
            output_facial_transformation_matrixes=True,
        )
        self._hand_model_path = store.path_for(HAND_LANDMARKER_MODEL)
        self._running_mode = running_mode

        self._object_detector = self._mp.tasks.vision.ObjectDetector.create_from_options(
            object_options
        )
        self._face_landmarker = self._mp.tasks.vision.FaceLandmarker.create_from_options(
            face_options
        )
        self._classifier = BehaviorClassifier(
            downward_pitch_threshold_degrees=config.downward_pitch_threshold_degrees,
            neutral_head_pitch_degrees=config.neutral_head_pitch_degrees,
            head_pitch_sign=config.head_pitch_sign,
            phone_hand_max_distance=config.phone_hand_max_distance,
        )

    def detect(self, frame: Any) -> DetectionResult:
        return self.classify(self.analyze(frame))

    def classify(self, evidence: VisionEvidence) -> DetectionResult:
        return self._classifier.classify(evidence)

    def analyze(self, frame: Any) -> VisionEvidence:
        if self._closed:
            raise RuntimeError("MediaPipe detector is closed")

        rgb_frame = self._cv2.cvtColor(frame, self._cv2.COLOR_BGR2RGB)
        image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb_frame)
        object_result = self._object_detector.detect(image)
        face_result = self._face_landmarker.detect(image)

        height, width = frame.shape[:2]
        person_count = 0
        person_confidence = 0.0
        phone_confidence = 0.0
        person_boxes: list[NormalizedBox] = []
        phone_boxes: list[NormalizedBox] = []

        for detection in object_result.detections:
            if not detection.categories:
                continue
            category = detection.categories[0]
            category_name = category.category_name or category.display_name
            score = float(category.score or 0.0)
            if category_name == "person":
                person_count += 1
                person_confidence = max(person_confidence, score)
                person_boxes.append(self._normalize_box(detection.bounding_box, width, height))
            elif category_name == "cell phone":
                phone_confidence = max(phone_confidence, score)
                phone_boxes.append(self._normalize_box(detection.bounding_box, width, height))

        hand_points: list[Point] = []
        if phone_boxes:
            hand_result = self._get_hand_landmarker().detect(image)
            for hand in hand_result.hand_landmarks:
                hand_points.extend(Point(float(point.x), float(point.y)) for point in hand)

        face_count = len(face_result.face_landmarks)
        face_boxes: list[NormalizedBox] = []
        for face in face_result.face_landmarks:
            x_values = [float(point.x) for point in face]
            y_values = [float(point.y) for point in face]
            if x_values and y_values:
                x_min = max(0.0, min(x_values))
                y_min = max(0.0, min(y_values))
                x_max = min(1.0, max(x_values))
                y_max = min(1.0, max(y_values))
                face_boxes.append(
                    NormalizedBox(
                        x=x_min,
                        y=y_min,
                        width=max(0.0, x_max - x_min),
                        height=max(0.0, y_max - y_min),
                    )
                )
        head_pitch_degrees: float | None = None
        matrices = face_result.facial_transformation_matrixes
        if len(matrices) == 1:
            head_pitch_degrees = pitch_degrees_from_transformation_matrix(matrices[0])

        return VisionEvidence(
            person_count=person_count,
            person_confidence=person_confidence,
            phone_boxes=tuple(phone_boxes),
            phone_confidence=phone_confidence,
            face_count=face_count,
            hand_points=tuple(hand_points),
            head_pitch_degrees=head_pitch_degrees,
            person_boxes=tuple(person_boxes),
            face_boxes=tuple(face_boxes),
        )

    @staticmethod
    def _normalize_box(box: Any, width: int, height: int) -> NormalizedBox:
        x_min = max(0.0, min(1.0, float(box.origin_x) / width))
        y_min = max(0.0, min(1.0, float(box.origin_y) / height))
        x_max = max(0.0, min(1.0, float(box.origin_x + box.width) / width))
        y_max = max(0.0, min(1.0, float(box.origin_y + box.height) / height))
        return NormalizedBox(
            x=x_min,
            y=y_min,
            width=max(0.0, x_max - x_min),
            height=max(0.0, y_max - y_min),
        )

    def _get_hand_landmarker(self) -> Any:
        if self._hand_landmarker is None:
            options = self._mp.tasks.vision.HandLandmarkerOptions(
                base_options=self._mp.tasks.BaseOptions(
                    model_asset_path=str(self._hand_model_path),
                ),
                running_mode=self._running_mode,
                num_hands=2,
            )
            self._hand_landmarker = self._mp.tasks.vision.HandLandmarker.create_from_options(
                options
            )
        return self._hand_landmarker

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._object_detector.close()
        self._face_landmarker.close()
        if self._hand_landmarker is not None:
            self._hand_landmarker.close()
