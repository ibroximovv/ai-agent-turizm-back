from __future__ import annotations

from django.contrib.auth import get_user_model
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from apps.accounts.api.serializers import (
    ChangePasswordSerializer,
    LoginSerializer,
    UserSerializer,
    UserWriteSerializer,
)
from apps.catalog.api.views import UUID_REGEX
from apps.common.permissions import IsAdminRole

User = get_user_model()


@extend_schema(
    tags=["Auth"],
    summary="Tizimga kirish",
    description="Email va parol evaziga access/refresh token hamda profil qaytaradi.",
)
class LoginView(TokenObtainPairView):
    serializer_class = LoginSerializer
    permission_classes = [AllowAny]


@extend_schema(tags=["Auth"], summary="Access tokenni yangilash")
class RefreshView(TokenRefreshView):
    permission_classes = [AllowAny]


@extend_schema(tags=["Auth"])
class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Chiqish",
        description=(
            "Refresh tokenni bekor qiladi. Access token o'z muddati tugaguncha "
            "amal qiladi, shuning uchun uni klientdan ham o'chiring."
        ),
        request=None,
        responses={205: None},
    )
    def post(self, request):
        refresh = request.data.get("refresh")
        if refresh:
            try:
                RefreshToken(refresh).blacklist()
            except (TokenError, AttributeError):
                # Blacklisting needs the optional app; a failure here is not
                # worth an error response — the client discards the token anyway.
                pass
        return Response(status=status.HTTP_205_RESET_CONTENT)


@extend_schema(tags=["Auth"])
class MeView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(summary="Joriy foydalanuvchi", responses={200: UserSerializer})
    def get(self, request):
        return Response(UserSerializer(request.user).data)

    @extend_schema(
        summary="Parolni almashtirish",
        request=ChangePasswordSerializer,
        responses={200: UserSerializer},
    )
    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(UserSerializer(request.user).data)


@extend_schema(tags=["Auth"])
@extend_schema_view(
    list=extend_schema(summary="Foydalanuvchilar ro'yxati (faqat admin)"),
    retrieve=extend_schema(summary="Foydalanuvchi tafsilotlari"),
    create=extend_schema(summary="Foydalanuvchi qo'shish"),
    partial_update=extend_schema(summary="Foydalanuvchini tahrirlash"),
    destroy=extend_schema(summary="Foydalanuvchini o'chirish"),
)
class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all()
    permission_classes = [IsAdminRole]
    lookup_value_regex = UUID_REGEX

    def get_serializer_class(self):
        if self.action in {"create", "update", "partial_update"}:
            return UserWriteSerializer
        return UserSerializer

    def create(self, request, *args, **kwargs):
        write = self.get_serializer(data=request.data)
        write.is_valid(raise_exception=True)
        user = write.save()
        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        write = self.get_serializer(
            self.get_object(), data=request.data, partial=kwargs.pop("partial", False)
        )
        write.is_valid(raise_exception=True)
        user = write.save()
        return Response(UserSerializer(user).data)

    @extend_schema(summary="Foydalanuvchi parolini tiklash", request=UserWriteSerializer)
    @action(detail=True, methods=["post"], url_path="set-password")
    def set_password(self, request, pk=None):
        user = self.get_object()
        password = request.data.get("password")
        if not password:
            return Response(
                {"password": "Majburiy maydon"}, status=status.HTTP_400_BAD_REQUEST
            )
        user.set_password(password)
        user.save(update_fields=["password", "updated_at"])
        return Response(UserSerializer(user).data)
