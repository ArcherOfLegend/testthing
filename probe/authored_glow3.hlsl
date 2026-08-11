// Generated from the Blender material XfBAD__IW_0__m00_ by io_umvc3_css.
// Target ps_3_0; register assignments taken from the shader being replaced.
sampler2D tAlbedo : register(s0);

struct PSIn {
    float4 vcol : TEXCOORD0;   // .w carries the interpolated alpha
    float4 aux  : TEXCOORD1;
    float2 uv   : TEXCOORD2;
};

float4 main(PSIn psin) : COLOR
{
    float3 n_Texture_Coordinate_UV = float3(psin.uv, 0.0);
    float3 n_Separate_XYZ_Y_v = n_Texture_Coordinate_UV;
    float3 n_Separate_XYZ_Y = n_Separate_XYZ_Y_v.yyy;
    float n_Color_Ramp_Color_f = saturate((n_Separate_XYZ_Y).x);
    float3 n_Color_Ramp_Color = lerp(lerp(lerp(lerp(lerp(lerp(float3(0.000000, 0.100000, 0.250000), float3(0.060000, 0.400000, 0.700000), saturate((n_Color_Ramp_Color_f - 0.000000) / 0.220000)), float3(0.300000, 0.750000, 1.000000), saturate((n_Color_Ramp_Color_f - 0.220000) / 0.180000)), float3(0.950000, 1.000000, 1.000000), saturate((n_Color_Ramp_Color_f - 0.400000) / 0.100000)), float3(0.300000, 0.750000, 1.000000), saturate((n_Color_Ramp_Color_f - 0.500000) / 0.100000)), float3(0.060000, 0.400000, 0.700000), saturate((n_Color_Ramp_Color_f - 0.600000) / 0.180000)), float3(0.000000, 0.100000, 0.250000), saturate((n_Color_Ramp_Color_f - 0.780000) / 0.220000));
    float4 n_Image_Texture_Color_t = tex2D(tAlbedo, psin.uv);
    float3 n_Image_Texture_Color = n_Image_Texture_Color_t.rgb;
    float3 n_Mix__Legacy__Color = lerp(n_Color_Ramp_Color, n_Color_Ramp_Color * n_Image_Texture_Color, saturate(1.000000));
    float n_Color_Ramp_Alpha_f = saturate((n_Separate_XYZ_Y).x);
    float3 n_Color_Ramp_Alpha = float3(lerp(lerp(lerp(lerp(lerp(lerp(0.000000, 0.280000, saturate((n_Color_Ramp_Alpha_f - 0.000000) / 0.220000)), 0.620000, saturate((n_Color_Ramp_Alpha_f - 0.220000) / 0.180000)), 1.000000, saturate((n_Color_Ramp_Alpha_f - 0.400000) / 0.100000)), 0.620000, saturate((n_Color_Ramp_Alpha_f - 0.500000) / 0.100000)), 0.280000, saturate((n_Color_Ramp_Alpha_f - 0.600000) / 0.180000)), 0.000000, saturate((n_Color_Ramp_Alpha_f - 0.780000) / 0.220000)), lerp(lerp(lerp(lerp(lerp(lerp(0.000000, 0.280000, saturate((n_Color_Ramp_Alpha_f - 0.000000) / 0.220000)), 0.620000, saturate((n_Color_Ramp_Alpha_f - 0.220000) / 0.180000)), 1.000000, saturate((n_Color_Ramp_Alpha_f - 0.400000) / 0.100000)), 0.620000, saturate((n_Color_Ramp_Alpha_f - 0.500000) / 0.100000)), 0.280000, saturate((n_Color_Ramp_Alpha_f - 0.600000) / 0.180000)), 0.000000, saturate((n_Color_Ramp_Alpha_f - 0.780000) / 0.220000)), lerp(lerp(lerp(lerp(lerp(lerp(0.000000, 0.280000, saturate((n_Color_Ramp_Alpha_f - 0.000000) / 0.220000)), 0.620000, saturate((n_Color_Ramp_Alpha_f - 0.220000) / 0.180000)), 1.000000, saturate((n_Color_Ramp_Alpha_f - 0.400000) / 0.100000)), 0.620000, saturate((n_Color_Ramp_Alpha_f - 0.500000) / 0.100000)), 0.280000, saturate((n_Color_Ramp_Alpha_f - 0.600000) / 0.180000)), 0.000000, saturate((n_Color_Ramp_Alpha_f - 0.780000) / 0.220000)));
    return float4(n_Mix__Legacy__Color, saturate((n_Color_Ramp_Alpha).x) * psin.vcol.w);
}
