/*
 *
 *  Wireless daemon for Linux
 *
 *  Copyright (C) 2021  Intel Corporation. All rights reserved.
 *
 *  This library is free software; you can redistribute it and/or
 *  modify it under the terms of the GNU Lesser General Public
 *  License as published by the Free Software Foundation; either
 *  version 2.1 of the License, or (at your option) any later version.
 *
 *  This library is distributed in the hope that it will be useful,
 *  but WITHOUT ANY WARRANTY; without even the implied warranty of
 *  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
 *  Lesser General Public License for more details.
 *
 *  You should have received a copy of the GNU Lesser General Public
 *  License along with this library; if not, write to the Free Software
 *  Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
 *
 */

#ifdef HAVE_CONFIG_H
#include <config.h>
#endif

#include <assert.h>
#include <stdio.h>

#include <ell/ell.h>

#include "src/dpp-util.h"
#include "src/util.h"
#include "ell/useful.h"

/*
 * B.2 Test Vectors for DPP Authentication Using P-256 for
 * Responder-only Authentication
 */
const char *i_proto_public_bytes = "50a532ae2a07207276418d2fa630295d45569be425aa634f02014d00a7d1f61a";
const char *r_boot_public_bytes = "09c585a91b4df9fd25a045201885c39cc5cfae397ddaeda957dec57fa0e3503f";
const char *r_boot_private_bytes = "54ce181a98525f217216f59b245f60e9df30ac7f6b26c939418cfc3c42d1afa0";
const char *r_proto_private_bytes = "f798ed2e19286f6a6efe210b1863badb99af2a14b497634dbfd2a97394fb5aa5";
const char *r_proto_public_bytes = "5e3fb3576884887f17c3203d8a3a6c2fac722ef0e2201b61ac73bc655c709a90";
const char *k1_bytes = "3d832a02ed6d7fc1dc96d2eceab738cf01c0028eb256be33d5a21a720bfcf949";
const char *k2_bytes = "ca08bdeeef838ddf897a5f01f20bb93dc5a895cb86788ca8c00a7664899bc310";
const char *ke_bytes = "c8882a8ab30c878467822534138c704ede0ab1e873fe03b601a7908463fec87a";
const char *mx_bytes = "dde2878117d69745be4f916a2dd14269d783d1d788c603bb8746beabbd1dbbbc";
const char *nx_bytes = "92118478b75c21c2c59340c842b5bce560a535f60bc37a75fe390d738c58d8e8";
const char *i_nonce_bytes = "13f4602a16daeb69712263b9c46cba31";
const char *r_nonce_bytes = "3d0cfb011ca916d796f7029ff0b43393";
const char *i_auth_bytes = "787d1189b526448d2901e7f6c22775ce514fce52fc886c1e924f2fbb8d97b210";
const char *r_auth_bytes = "43509ef7137d8c2fbe66d802ae09dedd94d41b8cbfafb4954782014ff4a3f91c";

#define HEX2BUF(s, buf, _len) { \
	unsigned char *_tmp = l_util_from_hexstring(s, NULL); \
	memcpy(buf, _tmp, _len); \
	l_free(_tmp); \
}

#define CHECK_FROM_STR(str, bytes, __len) \
({ \
	uint64_t __tmp[L_ECC_MAX_DIGITS]; \
	HEX2BUF(str, __tmp, __len); \
	assert(!memcmp(bytes, __tmp, __len)); \
})

static void test_key_derivation(const void *data)
{
	uint64_t tmp[L_ECC_MAX_DIGITS];
	const struct l_ecc_curve *curve = l_ecc_curve_from_ike_group(19);
	_auto_(l_ecc_point_free) struct l_ecc_point *i_proto_public = NULL;
	_auto_(l_ecc_point_free) struct l_ecc_point *r_boot_public = NULL;
	_auto_(l_ecc_scalar_free) struct l_ecc_scalar *r_boot_private = NULL;
	_auto_(l_ecc_scalar_free) struct l_ecc_scalar *r_proto_private = NULL;
	_auto_(l_ecc_point_free) struct l_ecc_point *r_proto_public = NULL;
	_auto_(l_ecc_scalar_free) struct l_ecc_scalar *m = NULL;
	_auto_(l_ecc_scalar_free) struct l_ecc_scalar *n = NULL;
	uint64_t k1[L_ECC_MAX_DIGITS];
	uint64_t k2[L_ECC_MAX_DIGITS];
	uint64_t ke[L_ECC_MAX_DIGITS];
	uint8_t i_nonce[16];
	uint8_t r_nonce[16];
	uint64_t r_auth[L_ECC_MAX_DIGITS];
	uint64_t i_auth[L_ECC_MAX_DIGITS];

	HEX2BUF(i_proto_public_bytes, tmp, 32);
	i_proto_public = l_ecc_point_from_data(curve,
						L_ECC_POINT_TYPE_COMPLIANT,
						tmp, 32);
	assert(i_proto_public);

	HEX2BUF(r_boot_public_bytes, tmp, 32);
	r_boot_public = l_ecc_point_from_data(curve,
						L_ECC_POINT_TYPE_COMPLIANT,
						tmp, 32);
	assert(r_boot_public);

	HEX2BUF(r_proto_public_bytes, tmp, 32);
	r_proto_public = l_ecc_point_from_data(curve,
						L_ECC_POINT_TYPE_COMPLIANT,
						tmp, 32);
	assert(r_proto_public);

	HEX2BUF(r_boot_private_bytes, tmp, 32);
	r_boot_private = l_ecc_scalar_new(curve, tmp, 32);
	assert(r_boot_private);

	HEX2BUF(r_proto_private_bytes, tmp, 32);
	r_proto_private = l_ecc_scalar_new(curve, tmp, 32);
	assert(r_proto_private);

	m = dpp_derive_k1(i_proto_public, r_boot_private, k1);
	assert(m);

	CHECK_FROM_STR(k1_bytes, k1, 32);
	l_ecc_scalar_get_data(m, tmp, sizeof(tmp));
	CHECK_FROM_STR(mx_bytes, tmp, 32);

	n = dpp_derive_k2(i_proto_public, r_proto_private, k2);
	assert(n);

	CHECK_FROM_STR(k2_bytes, k2, 32);
	l_ecc_scalar_get_data(n, tmp, sizeof(tmp));
	CHECK_FROM_STR(nx_bytes, tmp, 32);

	HEX2BUF(i_nonce_bytes, i_nonce, 16);
	HEX2BUF(r_nonce_bytes, r_nonce, 16);
	dpp_derive_ke(i_nonce, r_nonce, m, n, ke);

	CHECK_FROM_STR(ke_bytes, ke, 32);

	dpp_derive_r_auth(i_nonce, r_nonce, 16, i_proto_public, r_proto_public,
				r_boot_public, r_auth);
	CHECK_FROM_STR(r_auth_bytes, r_auth, 32);

	dpp_derive_i_auth(r_nonce, i_nonce, 16, r_proto_public, i_proto_public,
				r_boot_public, i_auth);
	CHECK_FROM_STR(i_auth_bytes, i_auth, 32);
}

int main(int argc, char *argv[])
{
	l_test_init(&argc, &argv);

	l_test_add("DPP test key derivation", test_key_derivation, NULL);

	return l_test_run();
}
